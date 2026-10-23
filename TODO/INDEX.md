# MBForge TODO index

This directory records active architecture and implementation plans.

## Current pipeline

`Extract → Markdown → Patent` is the registered pipeline, but the stages are
scheduled decoupled: import runs **Extract + Markdown** only and the document
rests at status `extracted` (readable, not yet analyzed), and **Patent runs on
demand** — per document or in batch (`POST /api/v1/documents/patent-analysis`)
— as a `patent`-only run that rebuilds its inputs from the SQL evidence. Both
entries run through the same queue; `enqueue(..., stages=...)` selects the
subset. Extract is the single producer — the layout/text/table producer and the
molecule pass (MolDet + MolParser) both run inside it — and mints and persists
the canonical `SourceEvidence` rows to SQLite itself. SQL is the only evidence
store (there is no branch artifact); Markdown assembles the readable document
from that evidence, and Patent publishes the unified facts artifact. Link and
Persist are removed from the active path.

## Activity data

**Phase A of [the activity extraction plan](../docs/plan-activity-extraction.md)
is implemented.** Printed readings are now first-class SQL rows: they are stored
whether or not a structure owns them, so the dataset is complete and the
extraction backlog is countable instead of silently dropped.

The design is two tables. `measurements` holds a reading exactly as the document
printed it — value, unit, comparator, evidence IDs, page, printed designation —
with **no structural requirement**. `measurement_attribution` holds the optional
`reading -> structure` links, zero or more per reading, filled in as association
improves. `measurements.evidence_grade` separates a printed figure (`measured`)
from a model output; Phase A writes only `measured`, and compute paths must
supply their own grade rather than reuse it.

Measured on the real corpus (`.tmp/e2e` artifacts): **36 artifact readings → 36
SQL rows, 0 dropped, 12 attributed**. Before this change the same data reached
SQL as 8 `molecules.activity` scalars.

What was wrong before: the only persisted activity was that scalar, written by
`documents/patent_facts.py::_derived_rows` → `activity_updates` →
`UPDATE molecules SET activity = ?, activity_type = ?, units = ?`. It dropped
every reading it could not attribute to a structure (across 18 artifacts: 526
entries, 144 carrying an `entity_id` = 27%, and **0 of 130 readings carrying a
`mol_id`**) and then kept only `measurements_by_smiles[...][0]` — **the first
reading per molecule**, discarding the document's other assays, targets and
doses. The `activities` table (34 columns) had no production writer at all:
`INSERT INTO activities` appeared only in tests, so `/api/v1/activities/...` and
the agent's `query_activities` returned empty for every real document.

Retired with it: `activity/matching.py::match_activities` (385 lines) and
`make_family_core_guard`, neither called by production code.
`activity/family_gate.py` keeps only `derive_family_core`, which
`tests/unit/pipeline/test_recover_labels.py` does use.

Still open: the `activity_match` review kind is declared in `domain/review.py`
and `service/dto/review.py`, read by `db/activity_store.py`, and produced by
nothing — it survives only as a read path for legacy rows.

## Model assets

Every model is downloaded into and read from one directory: the
`ResourceManager` cache (`library/models` by default, overridable via
`model_cache_dir`). Weights elsewhere on the machine (a repo-root `models/`,
`assets/models/`, the global HF/ModelScope caches) are deliberately ignored, so
a `ready` status always means the app can load the model from that directory.

Downloads are ModelScope-first with a HuggingFace fallback. The SDK channel
verifies its snapshot and hands off to the direct-HTTP channel when it writes
nothing, because the SDK does not raise when individual files fail. Both local
backends keep one process-wide model instance reused by every task, and
`foundation/inference/load_guard.py` cools down a failed load instead of
retrying it per crop.

The ingest queue does not claim a row until every model in
`REQUIRED_PIPELINE_MODEL_IDS` (`moldet`, `molparser`, `hiro_layout`,
`slanet_table`, defined beside `RESOURCE_CATALOG`) is `ready`. That set is the
single source of truth: `service/use_cases/pipeline/model_gate.py` reads it
through the runtime port, the queue worker consults the gate before
`_claim_rows`, and both `GET /api/v1/pipeline/worker/status` and
`/api/v1/readiness/summary` report the verdict. Blocked rows stay `pending` and
resume automatically once the downloads land — enqueueing is never gated.
`ppocrv6` is deliberately excluded: RapidOCR's weights ship with the
`rapidocr` package rather than the catalog, and OCR has a degradation path, so
gating on it would deadlock the queue.

## Docking

The docking worker (`server/docking/worker.py`) claims a `pending` job only when
`service/use_cases/docking/engine_gate.py` reports the engine ready — the same
gate-before-claim shape as the pipeline's model gate — so a missing engine or GPU
leaves jobs `pending` instead of failing them. Jobs left `running` by a previous
process are reset at worker startup. The engine
(`foundation/docking/engine.py`, UniDock-Pro) needs CUDA *and* a C++/CUDA binary
that no package index provides: it must be on PATH or named by
`MBFORGE_UNIDOCK_BIN`, and without it docking degrades to
`docking_unavailable` (503). The `docking` extra installs only the Python-side
preparation (`meeko`, `gemmi`, `unidock-tools`).

## LLM ownership

The chat LLM lives entirely in the `agent/` Node sidecar (port 18800): it owns
chat streaming, the provider model-list probe (`POST /v1/models`) and the
connectivity probe (`POST /v1/probe`). Python used to carry a LangChain client,
a LiteLLM mapping module, a provider default-URL table and a model-list probe in
`server/llm/`; that package, its `LlmCapability` port and the readiness
`probe-llm` endpoints are gone. Python now persists `AppConfig.llm` in
`settings.json` and readiness reports only whether those settings are complete
(config-derived, no network).

Both sides resolve `settings.json` the same way: `<source root>/library` when
`pyproject.toml` is present, else `~/MBForge`, overridable with
`MBFORGE_SETTINGS_PATH`. That single rule matters — the sidecar previously
defaulted to `~/MBForge/settings.json`, which does not exist in a source
checkout, so it read no settings at all and every saved key was silently lost.

## Research tools and Pi upgrade (2026-10-14)

- Migrated the Node SDK to pinned `@earendil-works/pi-coding-agent` / `pi-ai`
  1.2.0, replacing the deprecated `@mariozechner` packages. Model credentials and
  catalogs stay in memory; automatic project/user resources and native tools
  remain disabled.
- Added bounded SQL `search_library` with document/page/evidence provenance,
  keyword AND matching, snippet truncation and pagination. The research route
  resolves the turn credential's library even after the active library changes.
- Reused the official `@tavily/pi-extension@0.1.2` for `web_search` / `web_fetch`.
  MBForge supplies opt-in settings, per-turn limits, source URL restrictions,
  output bounds, timestamps and key redaction. No general plugin marketplace or
  second provider client was added. Patent sessions never load this extension.
- Research prompts now guide local lookup, evidence reading, information-gap
  identification, external source verification and assay-aware answers.
- Research chat has opt-in RCSB PDB structure search and Europe PMC publication
  search. Structure hits include organism, experimental method, resolution,
  deposited non-polymer component IDs/InChIKeys, citation metadata and direct
  PDB/mmCIF downloads. A component-name hit is not an exact compound match;
  PDB-format files can be downloaded and manually uploaded as receptors. The
  current receptor importer does not accept mmCIF or automatically fetch remote
  files. Search results remain conversation evidence rather than imported
  library records.
- Added the product-scoped `literature-search` and `patent-search` skills under
  `agent/skills/`. General and research chat expose only the fixed `load_skill`
  reader; it returns a registered guide/reference with a version and SHA-256,
  and does not accept file paths or change other tool permissions. The prompt
  routes explicit external literature/patent discovery to the matching skill;
  local Patent extraction stays document-only. Patent search remains Tavily
  public-web discovery, not an official patent-office API search.
- Prompt routing is layered: stable evidence policy and route selection are
  always present, skill descriptions form a compact index, the matching guide
  is loaded on demand, and references are loaded only for a specific unresolved
  question. Retrieval proceeds from scope and query plan through candidate
  checks, one purposeful refinement, source reading, stop conditions and cited
  reporting.
- The Agent skill contract is checked by `npm --prefix agent test`; no live
  provider or Tavily-key search was performed as part of this integration.
- Tavily cancellation stops waiting; the upstream SDK may continue its remote
  request. Its extension can spill unusually large responses to an OS temporary
  file before MBForge bounds the returned context. Live provider/key verification
  and scientific answer-quality evaluation remain pending.

## Layer boundaries

Repository and runtime ports live in the neutral `mbforge/ports/` (implemented
by `db`), and the cross-layer request/read models they reference in
`mbforge/contracts/` (re-exported by the `service` DTO modules), so `db`
implements the ports without importing `service`. The Markush SQL now lives in
`db/markush_*_store.py` behind `MarkushRepository`, so no `service`/`api` module
can obtain a raw connection. `foundation/inference/assets.py` defines the
`ResourceResolver` seam the composition root injects, so the inference backends
never import `server`.

## Known gaps

- Patent facts now also carry the printed **chemistry names**, **spectra/elemental
  lines** and **synthesis routes** (`PatentFactsArtifact.names` / `characterizations`
  / `synthesis_steps`), extracted by rule from SQL evidence with zero model calls.
  A zero-token sweep of all 13 corpus documents extracts 407 hydrogen spectra, 268
  mass spectra, 179 routes with 80 steps and 5 printed names, and every emitted
  string is a substring of the evidence row it cites (`fabricated = 0`). Elemental
  analysis has a live rule and no corpus hit. Forms and real strings:
  [docs/wiki/patent-extraction-forms.md](../docs/wiki/patent-extraction-forms.md) §11.
- **Association, not extraction, is the bottleneck.** The same sweep leaves 646 of
  854 extracted names/spectra/routes unattributed: the passage prints no designation
  the rules can bind, and rules cannot decide whether `77-A` or `77-B` owns a reading.
  Those residuals are the only thing the gap path sends to the model, which may
  associate and correct but never write a fact or a SMILES. Rules can detect a mass
  mismatch (`MS m/z` vs monoisotopic mass, ±0.6 Da) but not which structure is right,
  so a mismatch becomes a `smiles_correction` review item and a human decides; the
  `mol_id` is preserved and the fingerprint recomputed only on confirmation.
- An `assay_method_unresolved` gap no longer makes the model resend the reading it
  already extracted: a method-only answer is valid, and Python rebuilds the reading
  from the rule fact named by `rule_context.related_fact_id` (the value is copied,
  never retyped). One fact is bound per gap, so a refused 15-row table still binds
  its named reading only.
- **The previous live LLM pass submitted nothing; live quality remains unverified.**
  A live run (`patent_analysis.enabled=true`, LongCat-2.5-Preview) on CN121270515A
  and CN120329282A shows 14–24 tool calls, all of them `get_gap`, and `answered=0`,
  ending `no_submission` / `budget_exceeded`. Ruled out by instrumentation, not
  assumption: no sidecar HTTP failure (`postTool` now logs unreachable/failed), no
  backend refusal (`_failure` now logs every rejection), no contract rejection, and
  `get_gap` returns a gap every time. The runtime now refuses another gap while
  one is unanswered, and its four-turn per-gap budget resets only on an accepted
  answer, never on another fetch. Offline sidecar tests cover both guards; a new
  live run on 2026-10-16 verified four CYP3A4 table cells and their candidate
  references, but completed only 2/3 gaps in CN120329282A and 0/3 in CN121270515A
  within 240 seconds each. See [live acceptance](../docs/qa/patent-live-llm-20261016.md).
  A **full-stage** run on 2026-10-16 (same model and prompt version, its own sidecar
  built from `agent/dist`, 600 s wall / 240 s per request) answered **1 of 40** gaps
  in CN120329282A (7 turns, 602 s, ≈86 s per turn) and **0 of 28** in CN121270515A
  (3 turns — one per gap, none finishing inside its 240 s). The binding constraint is
  per-turn latency against the per-gap budget, not the tool surface: the accepted
  answer took 3 turns, one of them spent on a contract rejection it then fixed. See
  [the live association test](../docs/qa/patent-live-association-20261016.md).
  Scientific accuracy and complex-table stability remain unproven. The deterministic
  artifact remains the fallback (`llm_analysis_fallback`); fallback does not prove
  that structure recognition or scientific attribution is correct.
- Label aliases stored as lists now reach the gap as individual designations, and a
  candidate's `name` is read as a designation too (a label that lived only there
  used to be invisible to every rule). Automatic activity-to-structure attachment
  requires exactly one distinct structure for the printed label; duplicate
  candidates stay unresolved (`molecule_candidate_ambiguous`), and `Example 7` is
  not automatically `Compound 7`. The printed row designation takes precedence over
  a model-supplied normalized key. A designation no candidate carries is now
  **reported** (`molecule_label_unresolved`, info, keyed by the entry) instead of
  ending in silence, and `dangling_fact_reference` — a printed designation no
  section declares — reaches the model as a gap. Explicit model associations still
  require source review; a model-declared designation is published with
  `review_status="pending"`. MolDet/MolParser remain the structure producers: the
  LLM cannot invent or edit SMILES, and this change does not validate
  stereochemistry or recognition accuracy.
- A gap's excerpt is capped at the contract's own limit (`MAX_EXCERPT_CHARS`): a live
  run of CN120329282A failed the whole Patent stage because the excerpt budget (8000)
  exceeded the contract's cap (4000) and one invalid gap took the stage down.
- `storage/{doc_id}/pages/` has no writer in the active path: the removed Persist
  stage produced it, while the page reader still consumes it. `report.json` is
  written again by run finalization (`run/checkpoint.write_merged_report` →
  `LibraryLayout.report_json`), matching the reader. `artifacts/` and `runs/`
  have no writer either: `runs/` is only read, to keep new run ids from reusing
  existing directory names (`service/pipeline/run/ids.py`), and `artifacts/` is
  only deleted, by `LibraryStore.clear_pipeline_data`.
- Extract now classifies recognized image structures and atomically queues
  Markush scaffolds, fragments, and uncertain candidates with their canonical
  source-evidence links. Prose-only Markush definitions still need a separate
  text-candidate producer; they must not be fabricated as SMILES.
- The molecule↔evidence association is now persisted in `evidence.evidence_id`
  (pointing at the canonical `source_evidence` row); the legacy
  `text_molecule_links` table was dropped.
- An activity with no molecule is not representable in SQL: `activities.mol_id`
  is `NOT NULL` and nothing in `src/` inserts, `activity_match` review items have
  no producer, and `match_activities()` has no production caller. Such a
  measurement survives only in `patent_facts.json` `measurements[]`. The full
  cause list — including the silent entry-without-molecule case and the
  `name`-vs-`properties` label trap — with real text cases is in
  [docs/wiki/activity-association.md](../docs/wiki/activity-association.md).
- Import starts processing in the same request and the workspace lists every
  imported document right away: a fresh import rests at `pending` and shows as
  "待处理" while the queue reports the live stage. Auto-enqueue can be turned off
  (`ingest.auto_enqueue_on_import`); a failed enqueue leaves the document
  imported but unprocessed (`run_id` is `None`). Deleting a queue task clears
  that run's outputs (Markdown/report/pages/crops/molecule data) and returns the
  document to `pending`; only deleting the document card removes the source PDF.
- The `agent/` sidecar now has a Node test runner for Patent boundaries and
  durable research-session restoration with a local simulated provider. Its
  provider model-list and probe logic is still guarded by `tsc --noEmit` alone.
  Those contracts used to live in
  `tests/unit/test_llm_probe.py` and `tests/unit/routers/test_settings.py`,
  which were deleted with the Python implementation they covered.
- The frontend locale files carry roughly 340 keys no component references
  (whole `sar.*`, `welcome.*`, `project.*`, `pdf.patentFacts*`,
  `pdfToolbar.*` and `doc.*` groups among them). Only the removed-LLM cluster
  has been pruned; the rest is untouched pending a deliberate cleanup.
- The Markush workspace is unreachable: `frontend/src/components/markush/`
  (MarkushWorkspace, MarkushReviewPage, MarkushQueue, SiteEditor,
  EnumerationPanel) has no route in `App.tsx` and no sidebar entry, and
  `nav.markush` is an unreferenced locale key. Markush review is reachable only
  through the review center's `markush_link` items.
- SAR is a fail-closed stub: `/api/v1/sar` `build-matrix` returns `success:false`
  and `heatmap` an empty list, while `frontend/src/components/sar/` ships an
  R-group matrix/cliffs UI.
- Stale comments still describe behavior that no longer exists: the import path
  claims documents stay hidden until their run reaches a terminal status
  (`api/http/documents/library.py`, `server/ingest/worker.py`,
  `frontend/src/components/workspace/useWorkspaceQueueStatus.ts`) although
  `pending` is in `VISIBLE_DOCUMENT_STATUSES`; and `LibraryLayout`'s layout
  docstring lists `source.pdf` as the stored PDF although imports keep the
  original `file_name` (the accessor survives only as a legacy fallback in
  `resolve_document_pdf`).
- Deterministic activity extraction is proven on a 13-patent corpus (CN/US/WO/KR/
  JP/IL) but only 2 of those documents yield any measurement today: the others
  publish their activity as tables the parser refuses by design (split headers,
  structure-OCR columns, merged cells) or as glyph-damaged prose (`ICs0`,
  `ρIC50`). CJK bioassay headings, lettered US assay examples, Japanese
  `実施例` headings (400-page filing: 1 → 85 examples) and document-level bin
  legends are handled; the remaining JP obstacle is glyph damage, not headings.
  Every observed form — with the real strings, the issue code it raises and its
  state (handled / refused by design / open) — is cataloged in
  [docs/wiki/patent-extraction-forms.md](../docs/wiki/patent-extraction-forms.md).
  The measurable headroom, in order: table shapes still refusing (largest),
  CN120329282A's 24 measurements lacking an assay section form, and
  machine-translated filings whose heading labels were dropped in translation.

- **The live gap path consumes the model's associations.** Every accepted
  `PatentGapLink` (a printed designation + a recognized structure) is applied by
  `association.apply_gap_links` before the artifact is built, and `associate_facts`
  runs a second time on the result: a designation a section prints is resolved in
  place, a designation **no** section declares is declared by the link itself
  (the existing `CompoundEntry`, `review_status="pending"`), the reference is
  stored in the identity persistence reads (canonical SMILES, translated from the
  `mol_id` the payload carries), and the reading whose provenance cites the
  resolved designation carries it in `measurement.mol_id` — which is what lets it
  reach `molecules.activity` with no entry path. A designation the rules already
  resolved is never overwritten, and the relation reports are recomputed per pass,
  so the failure the model answered disappears instead of standing in the artifact.
  Corpus measurement (`.tmp/e2e/assoc_probe.py`, zero tokens): 310 entries, 63 with
  a structure, **247 designations now reported and handed over** as gaps instead of
  failing silently. Two things the live run forced: the work list is now sized to the
  turn budget (`max_gaps = min(DEFAULT_MAX_GAPS, max_model_turns // TURNS_PER_GAP)`,
  3 turns per gap measured live), so a run finishes and reports the rest as
  `skipped.over_cap` instead of dying mid-list; and `list_molecules(label=…)` answers
  "which structures carry this designation" in one call — the live model paged the
  catalogue blind twice per gap because a 130–355 candidate list only ever showed one
  page and refused a second lookup. Both are unit-verified; in the live run itself the
  model answered a *table* gap (`llm_links_applied = 0`), so the link path was not
  reached — see [the live association test](../docs/qa/patent-live-association-20261016.md).
  The v1 `PatentDraft.associations` field is still validated and
  never consumed, but nothing populates it: the sidecar wires only the gap tools
  (`submit-facts` has no caller), so the v1 draft path is dormant rather than
  half-wired.
- **Activity recall round (2026-10-16).** `uv run python .tmp/e2e/activity_recall.py`
  measures what the corpus prints against what the parser reads: **36 → 52
  measurements, 30 → 47 with a declared owner, parsable activity tables 3 → 6** of 31.
  The levers: the table metric vocabulary (a target-qualified CN header
  `CYP3A4(咪达唑仑)抑制率(%)` produced no metric at all, so one document's 24
  measurements were LLM-only), the merged label cell (`| 5 | ++++ | | ++++ |`), the
  header-declared example space (`实施例编号` + `2` is `@example:2`, not compound `2`),
  and suffix designations (`化合物77-A`). One rule change followed: the rule pass now
  declares the printed designation itself (`association._declare_entry`, reusing
  `CompoundEntry` with `review_status="pending"`), so the removed
  `dangling_fact_reference` has no producer left and no reading is ownerless. What
  remains is the **structure behind the designation** (247 of 310 corpus entries have
  no `entity_id`): the model binds it with `list_molecules(label=…)` plus a link. See
  [forms](../docs/wiki/patent-extraction-forms.md) §10 and
  [association](../docs/wiki/activity-association.md).
- **The worklist is shaped for the measured model budget.** Latency is ~86 s per turn
  and a gap takes ~3 turns, so one 40-minute run settles ~9 gaps; the corpus worklist
  had 735 entries. A refused table now travels `TABLE_ROWS_PER_GAP` rows at a time,
  family (spectra/name/route) and designation reports are grouped to
  `MAX_GAP_PASSAGES`, a gap is built only on **printed** rows, and an association issue
  citing the candidates' detection payloads resolves its rows through the **entry** that
  names the designation. Result: **735 → 142 gaps carrying 251 designations**, and
  CN120329282A's 40+ became 7, so one document is one run. Two live runs measured it:
  a designation-only one finished `complete=true` in 4 turns / 118 s and answered
  `no_attribution` because its gap was a payload (fixed); a full-stage one (7 gaps, 24
  turns / 1800 s) ran 17 turns / 27 min, accepted 3 answers (two assay methods became
  review candidates, the designation answer was again `unanswerable`) and exhausted the
  token budget with 4 gaps unprocessed. In both cases the refusal was *correct for what
  it was given* — and in the second, the 34 ambiguous designations had been silenced as
  `no_text_location` by the payload filter. The entry-aware resolution makes them
  answerable; it is not yet live-verified.
- **页级最简文本提问优于缺口契约包装（2026-10-17 实测）。** 同一模型、同一页面 payload：缺口
  契约版单轮 300–400 秒且不提交；两句话的最简文本版 24–47 秒给出答案，123 个数字里 1 个不在页内、
  23 个编号无一编造，覆盖规则 28 条读数中的 19 条。让模型卡住的是 prompt 里的契约/工具/提交框架，
  不是上下文体积（§8 的相反结论已更正）。
- **关联的瓶颈是索引，不是提问（2026-10-17 实测）。** 全语料 52 条规则读数**没有一条**带 mol_id；
  编号条目↔检出结构解析率 20%（63/314），结构带任何编号率 13%（343/2605）。关联链是跨页多跳
  （行 → 编号/实施例号 → example 小节 → 检出结构，CN121270515A 的 14 条绑定全部跨页，400 页文档里
  结构分布在 152–396 页），所以下一步是页级补 `编号 → 结构` 这一跳并落库，而不是加大 prompt。
  证据与三张实测表：`docs/qa/patent-live-association-20261016.md` §9。
- **"按页阅读"作为一个替代架构已被真实实验否定（2026-10-16）。** 用生产契约把一页做成一个 gap
  （页面证据 + 候选）跑真实模型：开放式措辞下 5 页里 4 页单轮 >300 秒超时、1 页答 `unanswerable`、
  0 条读数；有界措辞下 20 分钟 3 轮、0 次工具调用、0 条提交、0 条读数。单轮延迟随 excerpt 体积
  单调上升（0.7k→30 秒、1–2k→96 秒、3.7k→300–400 秒且不提交），所以**窄任务是承重设计**：
  放大任务不会让模型读得更多，只会让它推理到超时。要放宽必须先确定"单次预算 vs 页面规模"的可行
  边界。证据与两次运行的完整数据：`docs/qa/patent-live-association-20261016.md` §8。
- Review items are re-pended on every publication: `_queue_review_items` calls
  `set_review_item_status(item_id, kind, "pending")` for every remaining
  candidate unconditionally, so a previously rejected item that is still a
  candidate is resurrected to `pending` by any later re-run or decision publish.

## Active plans

- [Activity data extraction and persistence](../docs/plan-activity-extraction.md) — **Phase A implemented**: readings are first-class SQL rows independent of structure attribution. Phase B (compute layer: Boltz-2, reproducible `compute_runs`, `evidence_grade` for predictions) and Phase C (SAR, synthesis suggestions) are recorded with their preconditions and are not scheduled.
- [Patent analysis and an LLM-first research workspace](../docs/plan-patent-agent-harness.md) — frontend U0/U1/P4 and necessary SQL/session/task integration completed; [acceptance evidence](../docs/qa/research-workbench-20261013.md). P5 real-patent scientific evaluation remains pending; LLM analysis is opt-in.
- [Source layout reorganization](../docs/plan-source-layout-reorganization.md)
- [SLANet-1M as table parser on the Hiro-Layout path](../docs/plan-slanet-1m-table-parser.md)
- [Backend architecture](../docs/wiki/architecture.md)
- [Pipeline contract](../docs/wiki/pipeline.md)

## Conventions

- Treat `docs/wiki/pipeline.md` as the per-stage contract.
- Keep SQL source evidence separate from the shared `domain.molecule.Molecule`
  entity and inferred facts.
- `Molecule` is the only structure-bearing molecule domain object across
  detection normalization, correction, Markush handling, hydration, query,
  and future persistence. `ExtractionResult`/`DetectionSource` remain raw
  observations; `CompoundEntry` remains a document-level patent record.
- Cross-business-package imports use absolute `mbforge...` paths; relative
  imports are for a package and its immediate local modules.

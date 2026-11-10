# MBForge TODO index

This directory records active architecture and implementation plans.

## Agent molecule-recognition tool (2026-11-09)

A whole-document comparison on `CN120118069A` measured what the chat model can
do on its own: given page images it found the activity pages (98–102) and read
all 69 values exactly, but it could **not** emit a single SMILES from a drawn
structure (one structure page burned its full 24k-token budget on reasoning and
returned empty content). Structure reading therefore belongs to the local
detectors, exposed to the model as a tool instead of an expectation.

`recognize_molecules` now runs MolDetv2 + MolParser over one page of a stored
document and returns, per structure: SMILES, E-SMILES, pixel box, PDF-point box
(bottom-left origin, the overlay contract), detection score and OCR-read printed
labels. It is read-only and never persists anything.

- Service: `service/use_cases/molecule/recognition.py` (`recognize_page_molecules`).
  It takes `(library_root, doc_id)` and an absolute PDF path, so path policy
  stays with the caller.
- Capability: `recognize_molecules` (read-only, `service/capabilities/read.py`)
  resolves the stored PDF and returns the same result; it never persists.
- Agent wiring: the pi CLI receives it from the capability manifest; no
  sidecar-only tool remains.
- Tests: `tests/unit/services/test_molecule_recognition.py` protects the PDF-point
  box contract, the region filter and truncation visibility.

Pending: decide whether the model may cite a label→SMILES match as evidence
(currently it reports tool output, not a new fact).

## Table-embedded molecules (2026-11-06)

Structures drawn *inside* a table cell were being read as cell text: the table
producer runs SLANet-1M on the whole crop and recognizes every detected line
whose centre falls in a cell, so atom labels and bond glyphs became cell
content. Measured on the 13-document development corpus: up to **260
chemistry-looking cells in one document** (`0 HN. NH 0 CF3 N`, `N HN S CH3 O`),
and table-embedded molecules are the norm there (68/68 tables, 104/105, 56/64 in
the worst three; 409 molecules in one document).

`layout.mask_table_molecules` (default **off**) now makes the table read as
text: molecule boxes from the layout producer's own MolDet pass are blanked in a
copy of the table crop **for cell-text recognition only** (structure inference
still sees the original crop), and a `[MOL:n]` token is written into the cell
that holds the drawing, preserving its row/column position. The token → molecule
mapping (PDF points) rides on the region (`molecule_cells`), and evidence
minting replaces a token with the printed label the molecule pass read from the
crop (`name`, else `ocr_labels[0]`); an unlabelled molecule keeps its token
rather than an invented number. Non-table text evidence is unchanged, and a
table without embedded molecules behaves exactly as before.

Pending: run the 13-document A/B with the flag on, confirm table/measurement/
Patent outputs do not regress, then decide whether to default it on.
`scripts/table_mask_ab.py` runs that comparison over a library's table pages
(no writes). Measured so far (table pages only, chemistry-looking cells off →
on): CN121270515A 0 → 0 (8 tables, no table molecules — control),
KR20250121245A 12 → 0 (26 tables / 126 molecules masked), WO2025002360A1
15 → 3 (20/218), WO2025223036A1 265 → 3 (56/317), CN119504738A 10 → 0 (3/11,
rows and cells unchanged). Table structure counts were stable apart from model
run-to-run nondeterminism (one row on two documents). The full corpus run is
left to the script: the 400-page JP document makes a serial 13-document pass
long, and the five documents above cover clean, heavy and control shapes.

## Activity pair truth (2026-11-06)

Two deterministic defects are fixed on `CN119504738A` (the only document in the
local library): no model call, no re-extract, both covered by unit tests.

1. **A page-split activity table is read under its own page's header.** Table 1
   prints 14 IC50 readings across pp.124-125. Page 125 resumes with a data row and
   no header, so the Markdown converter promoted that row to the header and the
   parser dropped all 7 rows with **0 readings, 0 issues and no LLM gap** —
   invisible in every surface. `service/pipeline/activity/table_scan.py` now owns
   one table evidence row: direct parse, then cross-page header inheritance
   (adjacent page only, same column count, first cell a designation, no header
   band), then a refusal that is always reported. Inherited readings stay
   auditable through `table_header_inherited`, which cites both evidence rows.
   Measured: **7 → 14 readings, 3 → 7 structure links, 0 silent drops**.
2. **A disputed designation never becomes a published pair.** One structure is
   detected with labels `1` and `22` (p.91 prepares `21`), so the association
   refuses both and the reading keeps no attribution — but the declared-example
   join published `化合物1 IC50 64.6` beside that structure, so the artifact's
   `structure_activity` contradicted `measurement_attribution` and the export.
   The ambiguity issue now carries its `label_key` and
   `_declared_structure_activity` withholds that designation. Measured: the
   declared pairs equal the SQL attribution set (2, 4, 10, 24, 27, 30, 1A) and
   the compound-1 pair is gone. `candidate_label_keys` moved to
   `patent/candidate_labels.py` (three importers shared a private helper).

3. **The assay is declared in the body, not in the title.** `[0891]测试例1:MRGPRX2体外
   钙流测定试验` sits inside an example section, and the assay rule read section
   titles only, so all 14 readings carried `assay_method_unresolved` and no
   target. `rules/assay.py` now reads body assay blocks (`测试例` / `试验例` /
   `Test Example`); each block owns the evidence after it up to the next heading,
   and the association picks the method whose block cites the reading's own row
   when a section prints several assays. The receptor token also needed ASCII
   boundaries — `\b` does not fire between `MRGPRX2` and the CJK text after it.
   Measured: **14/14 readings carry `assay_method_id` and `target="MRGPRX2"`**,
   and `assay_method_unresolved` is gone. `assay_description` stays empty: no
   printed description flows into the method yet.
4. **A declaration without parentheses is still a declaration.** `(目标化合物11)`
   and `实施例17：目标化合物17的制备` both state the product; requiring a bare
   `(化合物N)` dropped them. Declared examples on this document: **21 → 39**, now
   covering every designation Table 1 prints. A molecule detection payload may no
   longer mint a declaration — it repeats nearby headings verbatim, which put a
   second copy of the same example on the detection's page.
Still open on the same document, measured: **24 of 450 recognised structures
print a designation** (11%), so 11/14/17/23/32/33 stay unowned even though the
document now declares an example for each of them; `assay_description` stays
empty because no printed description reaches the method; `review_items = 0`
because both mint inputs are empty (`review_candidates` needed the removed LLM
merge, and every `smiles_mass_mismatch` issue carries `mol_id = ""`).

## Unbound readings, honest coverage, read surface (2026-11-07)

Three ordered follow-ups are implemented and measured on the live library
(`CN119504738A`: 14 readings, 7 attributed).

1. **A reading with no structure is now a review item.** Publishing mints one
   `designation_unbound` item per unattributed reading whose designation's own
   example section drew structures (the scope is the section page range plus the
   reading page; a document that drew nothing there is a source fact, not a
   question). Each item carries the page candidates; confirming it with
   `choice=<candidate mol_id>` writes `measurement_attribution` with
   `method="human"` and marks the reading accepted. A choice outside the
   candidates is refused. Measured: **7 items** for the
   seven unowned readings (1, 11, 14, 17, 23, 32, 33), 4-8 candidates each, and
   the live queue is 211 rows (204 Markush + 7 unbound).
2. **Coverage no longer calls recoverable work undrawn.** `dataset_stats` now
   reads whether the document drew structures whose designation was never read
   and reports `label_not_read` instead of `designation_without_structure`.
   Measured on the same document: `{structure_detected_unmatched: 1,
   label_not_read: 6}` — five of which are the recovery targets, and the one
   `unmatched` is compound 1, whose structure carries a disputed label.
3. **The read surface answers dataset questions.** `query_activities` accepts an
   empty `doc_id` (library scope), `metric`, `min_value` and `max_value`, and each
   row carries its `reasons` classification instead of `[]`. The `activity_stats`
   route reports printed vs attributed plus the reason split, so a caller can
   check coverage before claiming there is no data.
   The activity HTTP route gained the same filters.

Still open from this pass: the export CSV does not carry the attribution
method/confidence, `query_activities` has no `has_more` cursor, and the
`measurements.review_status` flag still has no queue semantics of its own.
Tests: 434 unit tests pass (3 pre-existing recorrection environment errors), and
the new service/router tests cover minting, binding, candidate refusal, the
`label_not_read` classification and the value filter.

## AI review proposals (2026-11-07)

The assistant may file a review item at any time for a target a human has not
reviewed yet. A proposal is not a decision: it enters the review center as
`ai_review` with the target, the field, the value it suggests, the value the
store actually holds, the rationale and the evidence ids it read. A human
confirms or rejects it, and only that decision writes a value.

- Entry points: `POST /api/v1/review/propose` (any caller). The removed
  credential-scoped research route and its chat tool were the sidecar's delivery
  path; the HTTP endpoint remains.
- Idempotent and freeze-safe: one item per
  `(doc_id, target_kind, target_id, field)` (`stable_id`). A second proposal for
  the same field while it is pending **revises** that item (revision counter plus
  a bounded history of superseded proposals). Once a human confirms or rejects
  it, the item is in `confirmed`/`rejected` and every further proposal for that
  target is **refused** with `a human already decided this target`; nothing is
  overwritten. Reopening is a human action (`reopen`), never an AI one.
- Anti-hallucination: the target must exist (evidence rows and molecules are
  resolved before insert; an invented id is refused), and `before_actual` is read
  from the store next to the model's claimed `before`, so a wrong claim is
  visible in the item instead of trusted.
- What a confirm applies: a molecule `name` (through the existing review
  repository setter) is written on confirm; evidence text, readings, entries and
  designations are **record-only** — rewriting the source text or a reading is a
  pipeline change, so the confirmed item is the audit of the decision instead.
  Extending an applier is a deliberate, testable step per target kind.
- UI: `ai_review` is a filter kind in the review center with a before/after
  card (current store value vs suggested value, field, rationale).

Verified: propose → revise → human confirm applies the molecule name → further
proposal refused (service tests, including an invented target and a record-only
evidence target); the same chain through `POST /api/v1/review/propose` →
`/review/queue?kind=ai_review` → `/review/decide` (router test); the full unit
suite (425 passed) and the frontend lint/type-check.

### In-chat review and batch approval (2026-11-07) — historical

The chat-side version shipped with the removed research workspace and is gone.
What survives is server-side and still current: `POST /api/v1/review/decide`
for one item and `POST /api/v1/review/decide-filtered` for a bounded batch
(`limit` default 200, max 500). The filtered path resolves the filter server-side
and runs every matching pending item through its own decision handler, so the
model never chose what got approved and a kind-specific side effect is not
skipped; the response reports `updated`/`skipped`/per-item results. The review
center keeps its selection-based bulk action. `ResearchReviewEvent`, the
`ResearchEvent` union and the SSE card stream were deleted with the sidecar.

## Review AI assist (2026-11-06) — removed (2026-11-10)

The review center's model-suggested answers were removed with the CLI-only
cutover: `service/use_cases/review_assist.py`, `contracts/review_assist.py`, the
`ReviewAssistRuntime` port, the `review_assists` table and the sidecar's
`POST /v1/review-assist` provider call no longer exist. Also gone with it:
`review.max_items`, `review.auto`, `review.images`, the readiness probe for the
assistant, and the `payload.ai_assist` field on queue rows. The review center
remains a human-decision surface only — the deterministic pipeline mints the
items and a person confirms or rejects them; no model answer is stored beside
an item.

## Structure–activity export (2026-10-30)

[Export contract and real-corpus audit](../docs/qa/structure-activity-export-20261030.md).
The workspace now downloads selected documents (or one document from its menu)
as a ZIP containing matched readings, unresolved readings and exact SQL evidence.
The export uses the committed Patent snapshot, refuses stale sources, preserves
all assays and stereochemistry, and keeps review candidates separate from facts.
Original and canonical units/comparators are separate; known concentrations
convert coherently to nM, unknown units remain unchanged, and missing units are
never guessed. Missing-unit numeric disagreements were the LLM merge's job; that
merge was removed on 2026-11-10, so no current path resolves them. Rejected or identity-changed catalog structures cannot enter matched CSV.

A deterministic replay for 13 development PDFs, after refreshing two damaged
CN121270515A table regions with the current local producer, now produces
**48 readings: 16 matched pending review and 32 unresolved**, with every reading
retained exactly once. The earlier stored-extraction baseline was 41/14/27.
Nonconcrete/rejected crops no longer block a unique concrete designation match;
body references to starting materials no longer replace an example's product
identity. Lost-rowspan headers are quarantined, not shifted by guesswork.
The refreshed selectivity table has the correct MRGPRX1–4 columns. Independent
source-image review found stereo errors in both CN121270515A final-product
recognitions; these remain unresolved and are not added as correct pairs.
These development counts are not precision/recall or scientific validation.
Next: adjudicated structure–reading–assay–source tuples, evidence-backed product
association, stereo review and missing assay context.

## Current Patent harness (2026-10-30) — historical

[Harness implementation and real-provider audit](../docs/qa/patent-harness-20261030.md)
records citable work/context packets, the exported schema as the then-actual Pi
tool contract, exact printed label/value-cell checks (`source_quote` + zero-based
`source_column`), stable work anchors and example namespaces. Four v4.2
real-provider work-chunk trials returned 6, 22, 0 and 1 text-supported readings;
the actual publisher preserved their column provenance as review candidates in
isolated SQL backups, with no new LLM structure links. The zero-result trial
correctly refused damaged OCR; these counts are not whole-page recall. The
printed positive control in CN120943813A p95 now stays in the deterministic
five-reading table, with IC50 preferred over generic activity wording.
Historical provider failures are retained. These are development samples of the
LLM gap path that was removed on 2026-11-10; the deterministic pipeline is the
only Patent path. Cell ownership does not prove assay semantics. The v4.3 follow-up fixes the generic
unit contract: dimensionless pIC50 no longer needs a missing-unit declaration,
while concentration readings still do. Physical units on log endpoints are
rejected; old drafts with a declared missing log unit remain readable.
The v4.3 fresh trial exhausted its gap budget after a structure lookup; v4.4
therefore exposes only excerpt/submit tools to bound table sessions. Separate
association tasks retain structure queries. Unitless pIC50 has passed isolated
tool validation and SQL publication replay. A v4.4 real-provider retest returned
E020 pIC50 6.9 in one turn/submit call (9,178 tokens, 59.675 s), also passing SQL
publication audit. This remains one work chunk; latency gains are not established.

## Current extraction experiments (2026-10-29)

[OCR/OXR bottleneck investigation](../docs/qa/patent-ocr-bottleneck-20261029.md)
records a fresh 13-document rule baseline, direct LLM calls and isolated 4090
server preparation. The baseline is 43 readings / 11 linked to structures, not
the older 52-reading snapshot. A reproduced error assigned an OCR-dropped `6`
to `5` in CN121270515A p20. Cross-column label inheritance is removed; the
ambiguous table now goes to review, leaving 36 readings / 11 structure-linked.
The old-SQL baseline is unchanged by later image fixes. On 8 freshly detected
tables, a 2-pixel cell/text tolerance restores printed `6` without changing other
cells; explicit HTML spans repair an observed MRGPRX1-4 target shift. Mass-only
empty-reading pairs are removed and declared-example joins respect their
namespace. A JP grouped-interval LLM experiment preserves clean-text lists and
identifies a printed conflict for example 258; noisy OCR exhausted its budget.
OXR has now completed 6 frozen-crop requests on the 4090: it restores all
three US structure-table readings and clean JP intervals. The parser now accepts
the structure table's explicit header beneath a spanning title (3 readings);
the assay-only table still needs evidence-scoped metric context. Explicit column
targets now survive SQL publication. An omp review exposed silent loss of malformed
span output; raw HTML is now retained for review with a warning and failure count.
The test service was stopped; no production backend switch
has been made. See the report for the unresolved association/interval work.

## Focus (2026-11-02)

The product scope is the patent reader: import → layout/OCR/table → source
evidence → facts and measurements → review/export. The agent surface is the pi
CLI; the web conversation and its research tools were removed on 2026-11-10.
Removed from the active surface: the notes /
knowledge base, the fake molecule Analytics/Relations panel and its
cluster/relation/analog/substructure stubs, the Markush attachment-site and
enumeration API, and the chat landing page (`/` now opens `/workspace`).

Reading UX pass: the viewer now restores page/zoom/continuous mode and overlay
choices per document, opens result views in focus mode (`f` toggles it), offers
fit-width/fit-page and 50–500% zoom, can hide molecule/layout/text layers,
highlights an evidence paragraph or PDF box in both directions, and the
Markdown reader has a heading TOC plus clickable page-marker links that open the
PDF at that page.

## Code weight pass (2026-11-04)

Deleted the unwired `foundation/chemname` vendored parser (2,511 lines) and
`service/pipeline/examples`, plus 29 dead symbols that had no caller outside
their own definition. `patent_stage.py` shrank 1,917 → 990 lines by moving the
rule extractors into `service/pipeline/patent/rules/`; `molecule_store.py`
shrank 1,026 → 707 by moving detection I/O and candidate persistence into
`detection_store.py` and `molecule_candidates.py`. The six patent test files
went 4,503 → 4,170 lines with no public contract lost. CI now enforces vulture,
import-linter layer contracts and a file-size budget
(`[tool.vulture]`, `.importlinter`, `scripts/check_file_sizes.py`).

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

A table that breaks across a page is now read as one table: a headerless
continuation reuses the previous evidence row's activity header when the column
count matches and the fragment sits on the adjacent page
(`activity/parsing/tables.py::parse_activity_table_continuation`). On
CN119504738A pp.124–125 (Table 1) that took the document from 7 to 14 readings;
the same run attributes 7 of them, so 7 molecules carry `activity`/`activity_type`/
`units` where 3 did before. Readings whose printed designation has no unambiguous
recognized structure (missing or duplicated OCR labels) stay unattributed and
pending review rather than guessed.

An earlier development replay (`.tmp/e2e` artifacts): **36 artifact readings → 36
SQL rows, 0 dropped, 12 attributed**. Before this change the same data reached
SQL as 8 `molecules.activity` scalars.

What was wrong before: the only persisted activity was that scalar, written by
`documents/patent_facts.py::_derived_rows` → `activity_updates` →
`UPDATE molecules SET activity = ?, activity_type = ?, units = ?`. It dropped
every reading it could not attribute to a structure (across 18 artifacts: 526
entries, 144 carrying an `entity_id` = 27%, and **0 of 130 readings carrying a
`mol_id`**) and then kept only `measurements_by_smiles[...][0]` — **the first
reading per molecule**, discarding the document's other assays, targets and
doses. The legacy `activities` table and the `activity_match` review kind were removed
with `db/activity_store.py` and `activity/family_gate.py`; no read path or
test-only producer remains. Readings live only in `measurements`.

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

## LLM ownership

The pi CLI (`agent/src/extension.ts` + `agent/src/capabilities.ts`) is the only
thing that talks to an LLM provider. It reads the `llm` section of
`settings.json`, and pi owns provider login, model switching and sessions. There
is no Node HTTP server, no `POST /v1/models` model-list probe and no
`POST /v1/probe` connectivity probe. Python used to carry a LangChain client, a
LiteLLM mapping module, a provider default-URL table and a model-list probe in
`server/llm/`; that package, its `LlmCapability` port and the readiness
`probe-llm` endpoints are gone. Python persists `AppConfig.llm` and readiness
reports only whether those settings are complete (config-derived, no network);
the frontend no longer fetches a provider model list or tests a connection.

Both sides resolve `settings.json` the same way: `<source root>/library` when
`pyproject.toml` is present, else `~/MBForge`, overridable with
`MBFORGE_SETTINGS_PATH`. That single rule matters — when the agent defaulted to
`~/MBForge/settings.json`, a source checkout read no settings at all and every
saved key was silently lost.

## Research tools and Pi upgrade (2026-10-14) — removed (2026-11-10)

The research workspace, its SQL `search_library` tool, the optional Tavily
`web_search` / `web_fetch` extension, the RCSB PDB and Europe PMC searches, the
skill-routing prompt stack and the research/review SSE streams were removed with
the CLI-only cutover. `@tavily/pi-extension` is no longer a dependency, the
web-search settings and keys are gone from `AppConfig`, and no research route,
`research_sessions` table or `research_task_requests` queue hook remains. What
replaces them is the pi CLI with the capability tools generated from
`/api/v1/capabilities`; `agent/skills/` and `agent/schemas/` were deleted with
the cutover, so no skill or schema artifact remains.

## Layer boundaries

Repository and runtime ports live in the neutral `mbforge/ports/` (implemented
by `db`), and the cross-layer request/read models they reference in
`mbforge/contracts/` (re-exported by the `service` DTO modules), so `db`
implements the ports without importing `service`. The Markush SQL now lives in
`db/markush_candidates.py` and `db/markush_transitions.py` behind
`MarkushRepository`, so no `service`/`api` module can obtain a raw connection. `foundation/inference/assets.py` defines the
`ResourceResolver` seam the composition root injects, so the inference backends
never import `server`.

## Recognition order and value rules (2026-10-23)

- `source_evidence` now persists `reading_order` (zero-based inside the page);
  `list_source_evidence` orders by it, so a two-column page is read column-major
  in the Patent stage. Legacy rows keep `0` and fall back to the geometric order
  until the document is re-extracted.
- `match_section_heading` normalizes digit-separating spaces and full-width
  digits before matching, so `実施例 1 0 3` and `実施例1 04` yield `103`/`104`
  without rewriting the stored `heading_line`; the range `実施例２および3` is
  normalized but still refused as one section.
- `ND`/`NA`/`NT` are missing values: `_qualitative_rank` no longer assigns rank
  `0`, and the table parser excludes them from the completeness count, so a row
  with `ND` does not become an inactivity measurement.
- Covered by `tests/unit/core/test_evidence.py`,
  `tests/unit/services/test_source_evidence.py`,
  `tests/unit/pipeline/test_sections_sql.py`,
  `tests/unit/pipeline/test_activity_normalization.py` and
  `tests/unit/pipeline/test_activity_parsing.py`.

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
- **(Historical) The live LLM gap pass submitted nothing; live quality was never
  verified, and the path was removed on 2026-11-10.**
  A live run (`patent_analysis.enabled=true`, LongCat-2.5-Preview) on CN121270515A
  and CN120329282A shows 14–24 tool calls, all of them `get_gap`, and `answered=0`,
  ending `no_submission` / `budget_exceeded`. Ruled out by instrumentation, not
  assumption: no agent HTTP failure (`postTool` now logs unreachable/failed), no
  backend refusal (`_failure` now logs every rejection), no contract rejection, and
  `get_gap` returns a gap every time. The runtime now refuses another gap while
  one is unanswered, and its four-turn per-gap budget resets only on an accepted
  answer, never on another fetch. Offline agent tests cover both guards; a new
  live run on 2026-10-16 verified four CYP3A4 table cells and their candidate
  references, but completed only 2/3 gaps in CN120329282A and 0/3 in CN121270515A
  within 240 seconds each. See [live acceptance](../docs/qa/patent-live-llm-20261016.md).
  A **full-stage** run on 2026-10-16 (same model and prompt version, its own agent
  server built from `agent/dist`, 600 s wall / 240 s per request) answered **1 of 40** gaps
  in CN120329282A (7 turns, 602 s, ≈86 s per turn) and **0 of 28** in CN121270515A
  (3 turns — one per gap, none finishing inside its 240 s). The binding constraint is
  per-turn latency against the per-gap budget, not the tool surface: the accepted
  answer took 3 turns, one of them spent on a contract rejection it then fixed. See
  [the live association test](../docs/qa/patent-live-association-20261016.md).
  Scientific accuracy and complex-table stability remain unproven. The deterministic
  artifact is now the only Patent output, so there is no LLM fallback mode any more.
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
- The unused `pages/`, `artifacts/` and `runs/` layout paths and their readers,
  writers and id-collision scan were removed. `report.json` is written by run
  finalization (`run/checkpoint.write_merged_report` →
  `LibraryLayout.report_json`).
- Extract now classifies recognized image structures and atomically queues
  Markush scaffolds, fragments, and uncertain candidates with their canonical
  source-evidence links. Prose-only Markush definitions still need a separate
  text-candidate producer; they must not be fabricated as SMILES.
- The molecule↔evidence association is now persisted in `evidence.evidence_id`
  (pointing at the canonical `source_evidence` row); the legacy
  `text_molecule_links` table was dropped.
- A reading with no molecule is first-class: `measurements` stores it with no
  structural requirement and `measurement_attribution` fills links in later.
  The removed `activities.mol_id` `NOT NULL` table no longer blocks such rows.
  The full cause list — including the silent entry-without-molecule case and the
  `name`-vs-`properties` label trap — with real text cases is in
  [docs/wiki/activity-association.md](../docs/wiki/activity-association.md).
- Import starts processing in the same request and the workspace lists every
  imported document right away: a fresh import rests at `pending` and shows as
  "待处理" while the queue reports the live stage. Auto-enqueue can be turned off
  (`ingest.auto_enqueue_on_import`); a failed enqueue leaves the document
  imported but unprocessed (`run_id` is `None`). Deleting a queue task clears
  that run's outputs (Markdown/report/crops/molecule data) and returns the
  document to `pending`; only deleting the document card removes the source PDF.
- The `agent/` workspace is CLI-only and guards itself with `tsc`
  (`npm --prefix agent run check`). No agent test files remain, so `npm test`
  compiles and then finds nothing under `dist/*.test.js`; the simulated provider
  and model-list/probe code are gone. Those contracts used to live
  in `tests/unit/test_llm_probe.py` and `tests/unit/routers/test_settings.py`,
  deleted with the Python implementation they covered; the later agent-side
  tests were deleted with the sidecar.
- The frontend locale files were pruned to keys the components reference;
  dynamic-key prefixes (`nav.*`, `mol.status.*`, `errors.*`, …) were preserved.
- Markush classification and review remain; the unreachable frontend workspace,
  its HTTP client, and the attachment-site/enumeration API were removed. Extract
  still queues scaffolds/fragments/candidates, and `markush_link` review items
  remain in the review center.
- SAR was removed: the fail-closed `/api/v1/sar` stub and
  `frontend/src/components/sar/` are gone. The follow-up molecule analysis
  panel (Analytics/Relations) was also removed: every backend function it called
  threw “no HTTP route available yet”. MoleculeLibrary keeps the list, detail,
  correction and bulk actions. Reintroducing SAR requires the Phase C
  preconditions in [the activity plan](../docs/plan-activity-extraction.md).
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

- **(Historical) The live gap path consumed the model's associations.** Every accepted
  `PatentGapLink` (a printed designation + a recognized structure) was applied by
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
  The agent wiring that hosted only the gap tools was deleted with that path, as
  were every `patent_analysis.*` setting and the `llm_analysis_fallback` mode, so
  no LLM Patent stage exists to run this flow.
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
- ~~Review items are re-pended on every publication.~~ **No longer true:**
  `review_audit.insert_review_item`'s `ON CONFLICT` clause updates the payload
  but not `status`, and `set_review_item_status` is called only from the human
  decision path (`service/use_cases/review_queue.py`). A rejected item that is
  still a candidate keeps its status across re-runs.

- **The relation-pair contract is accepted but not implemented.**
  `page_geometry`, `label_anchor` and `relation_pair` exist only in
  [ADR 0001](../docs/adr/0001-relation-pair-contract.md). The write path still
  stores canonical SMILES in `CompoundEntry.entity_id`, reports
  `structure_status="resolved"` without a verification axis, and drops a Markush
  candidate after `molecule_candidate_rejected`. The
  [gold standard](../docs/plan-gold-standard.md) has a development manifest
  (`tests/gold/manifest.json`, 13 documents) and a validator. Unadjudicated
  pilot annotations now cover five documents / 36 records
  (`tests/gold/annotations/*.pilot.jsonl`); the first-document findings are in
  [the pilot report](../docs/qa/gold-pilot-cn121270515a-20261023.md) and the
  cross-document rules in
  [patent layout rules](../docs/wiki/patent-layout-rules.md). There is no
  held-out split and no pair-level metric yet.

## Active plans

- [Relation-pair contract](../docs/adr/0001-relation-pair-contract.md) and
  [gold standard](../docs/plan-gold-standard.md) — **ADR accepted, tables not
  yet applied**. First implementation step is the `label_anchor` index in
  Extract, then the pair write path. Pilot annotations now cover five documents
  / 36 records in `tests/gold/annotations/`; the layout survey is
  [patent layout rules](../docs/wiki/patent-layout-rules.md). Human adjudication
  and the held-out split are pending.
- [Activity data extraction and persistence](../docs/plan-activity-extraction.md) — **Phase A implemented**: readings are first-class SQL rows independent of structure attribution. Phase B (compute layer: Boltz-2, reproducible `compute_runs`, `evidence_grade` for predictions) and Phase C (SAR, synthesis suggestions) are recorded with their preconditions and are not scheduled.
- [Source layout reorganization](../docs/plan-source-layout-reorganization.md)
- [Capability platform](../docs/plan-capability-platform.md)
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

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

## Known gaps

- `storage/{doc_id}/pages/` has no writer in the active path: the removed Persist
  stage produced it, while the page reader still consumes it. `report.json` is
  written again by run finalization (`run/checkpoint.write_merged_report` →
  `LibraryLayout.report_json`), matching the reader.
- Extract now classifies recognized image structures and atomically queues
  Markush scaffolds, fragments, and uncertain candidates with their canonical
  source-evidence links. Prose-only Markush definitions still need a separate
  text-candidate producer; they must not be fabricated as SMILES.
- The molecule↔evidence association is now persisted in `evidence.evidence_id`
  (pointing at the canonical `source_evidence` row); the legacy
  `text_molecule_links` table was dropped.
- Import starts processing in the same request and the workspace lists every
  imported document right away: a fresh import rests at `pending` and shows as
  "待处理" while the queue reports the live stage. Deleting a queue task clears
  that run's outputs (Markdown/report/pages/crops/molecule data) and returns the
  document to `pending`; only deleting the document card removes the source PDF.
- The `agent/` sidecar has no test runner, so its provider model-list and probe
  logic is guarded by `tsc --noEmit` alone. Those contracts used to live in
  `tests/unit/test_llm_probe.py` and `tests/unit/routers/test_settings.py`,
  which were deleted with the Python implementation they covered.
- The frontend locale files carry roughly 340 keys no component references
  (whole `sar.*`, `welcome.*`, `project.*`, `pdf.patentFacts*`,
  `pdfToolbar.*` and `doc.*` groups among them). Only the removed-LLM cluster
  has been pruned; the rest is untouched pending a deliberate cleanup.

## Active plans

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

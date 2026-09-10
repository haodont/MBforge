# MBForge Pipeline — Stage Reference

> **Last verified:** 2026-09-09
> **Canonical model:** **4 registered stages** with one fixed initial fork (`pipeline/stages/*.py` + `StageExecutor`)
> **Entry point:** `mbforge.pipeline.runner.run_pipeline(pdf_path, library_root, …)`  
> If this file drifts from code, **the code wins**.

## At a glance

```
PDF
 → Extract ∥ Detection  (independent page-evidence producers)
 → Markdown             (joined evidence → document.md)
 → Patent
```

Orchestrator: `pipeline/runner.py`  
Shared state: `pipeline/context.py:PipelineContext`  
Contract: `pipeline/stages/base.py:StageExecutor` → `StageResult`  
Runtime visibility: queue status, current stage, checkpoints, and pipeline events.

The initial Extract/Detection fork is explicit in `runner.py`; it is not a
general DAG engine. Rough Markdown is an internal intermediate, and only
MarkdownStage owns the final `document.md` writer. Patent is the current
endpoint; Link source code has been removed and Persist remains unregistered.
Patent also materializes only activity-backed concrete molecules into the
existing molecule table.

At the join boundary, the runner deduplicates `SourceEvidence` by
`evidence_id`, gives overlapping MolDet `molecule` evidence priority over
`image_region` evidence, then indexes the batch in one SQLite transaction.
The v2 runtime reads source evidence facts (`page`, `bbox`, `raw_text`,
`coref`, `kind`) from `{library_root}/.mbforge/library.db`, which is the only
evidence store. After Join, the readable Extract branch records the final IDs
on its text spans. Missing SQL evidence is an error, with no JSON fallback.

---

## Stage table

| # | Stage class | Key helpers | Purpose | Primary outputs |
|---|---|---|---|---|
| 1 | `ExtractStage` | `extract_text.extract_pdf_text` | Full-page cloud OCR (PaddleOCR) — every page rendered at 144 DPI and OCR'd; uniform text/table spans and PDF bottom-left coordinates; a page that yields no OCR text after retries fails the whole document | run-scoped ExtractArtifact |
| 2 | `DetectionStage` | `extract_molecules_from_pdf`, MolDetv2, MolParser | Independent raw molecule bbox/crop results; normalization waits for Join | run-scoped DetectionArtifact |
| 3 | `MarkdownStage` | `write_rough_markdown`, `insert_esmiles_blocks` | SQL-backed joined evidence → deterministic page assembly → final Markdown | `storage/{doc_id}/document.md` |
| 4 | `PatentStage` | SQL evidence section/activity parsers | One deterministic facts pass over `SourceEvidence.raw_text`; materialize eligible molecules | `storage/{doc_id}/patent_facts.json` and eligible rows in SQLite `molecules` |

HTTP twin for detection path: `routers/molecule/moldet.py` (page extract).

Knowledge-base search and Wiki read endpoints are separate from PDF ingestion.
The registered pipeline does not build or refresh those artifacts.

---

## Per-stage notes

### 1 — Extract

- **OCR-only (no native text double-track):** every page is rendered at 144 DPI
  and sent through the cloud OCR chain; the `_OCR_MIN_CHARS`/`ocr_fallback`
  native fallback and `build_from_document` were removed. OCR runs with bounded
  concurrency and per-page retry; any page that yields no text after retries
  fails the whole document (no partial evidence is ever ingested).
- OCR chain (cloud-only): PaddleOCR. MinerU and GLM-OCR backends were removed
  (2026-09-07); existing settings.json entries for them are ignored.
- Evidence `kind` produced by the OCR layout and Join: `text_span`, `table_span`
  (a whole table block, formerly `table_cell`), `image_region`, `ocr_label`, and
  `molecule` (from Detection). A `block_type=2` OCR block maps to `table_span`;
  there is no cell-level evidence in the current contract.
- Config: `AppConfig.ocr` via `load_global_config()` / settings UI — not a separate `configs/ocr.yaml` runtime file.

### 2 — Detection (molecule evidence)

- Detector: **`backends/moldet_v2_ft.py`** (YOLO26n FT — molecule bounding boxes only).
- Recognizer: MolParser → SMILES; normalize/dedup via RDKit + element whitelist.
- Crops are archived before a candidate is published. During an active run they
  are staged and later promoted to **`storage/{doc_id}/crops/`**.
- Coref identifier detection and identifier OCR are no longer part of this
  stage. The detector result is normalized to image-relative molecule boxes;
  MolParser recognizes each molecule crop.
- Detection publishes raw `ExtractionResult` records; malformed E-SMILES or
  rejected candidates remain reviewable but are not rendered into Markdown.

### 3 — Markdown (document + ESMILES projection)

- Reads the SQL-backed joined v2 evidence context from Extract and Detection;
  SQLite (`source_evidence`) is the only evidence store.
- Rough Markdown is temporary; this stage owns the durable `document.md` write.
- Text evidence keeps its Extract order; images and accepted E-SMILES blocks
  use page geometry, with image-before-molecule tie-breaking.

#### Molecule registration tool fallback

When image molecule detection returns no observations, the Markdown stage can
optionally run one cloud-only LLM tool-call pass over the extracted document
text. Enable it with `llm.molecule_tool_enabled` and limit the submitted source
with `llm.molecule_tool_max_chars` (default `16000`). The model can call
`submit_molecule_candidate` once per explicit structure; the tool records only a
document-scoped observation and returns deterministic SMILES normalization and
Markush/review status. It never writes SQL or overrides the Markush classifier.

The existing normalization, context correction, persistence, and review gates
are reused after the tool pass. Text-only observations are persisted as text
evidence, not as image evidence. The feature is disabled by default and is
rejected for local/self-hosted endpoints; provider failures remain visible as
`MOLECULE_TOOL_UNAVAILABLE` warnings.

### 4 — Patent

- Uses `pipeline/sections.py` to segment Chinese and English example,
  preparation, comparison, and reference headings directly from ordered SQL
  `text_span`/`table_span` rows.
- Reads `SourceEvidence.raw_text` once for entries, examples, assay methods,
  and measurements. No Markdown character ranges, map file, PDF fallback, or
  RapidOCR recovery path participates in this stage.
- Measurements use the existing `ActivityMeasurement` shape. Prose values use
  the actual text evidence IDs; a simple table uses its single whole-table
  `table_span.evidence_id`. Complex or unsupported tables produce an issue and
  no guessed measurements.
- Patent also performs exact-token measurement→entry and measurement→assay
  associations, and merges verified Detection evidence IDs into matching
  entries. A successful entry-candidate association records the existing
  canonical SMILES in `entry.entity_id`. Ambiguous or rejected candidates
  remain facts with review issues.
- Only candidates with a concrete canonical SMILES and at least one linked
  measurement are written to `molecules`; the first measurement populates the
  existing `activity`, `activity_type`, and `units` aggregate fields.
- `storage/{doc_id}/patent_facts.json` is the only interpretation artifact. It stores IDs and
  normalized values, not copied source blocks or new row/column entities.

### Later — Persist (not executed here)

The current runner stops after Patent. The former Link stage, Link artifact,
and Link domain model are no longer part of the repository. Patent's narrow
activity-backed molecule materialization is active; Persist code is retained
but unregistered for the remaining database/API projections.

- Joined `SourceEvidence` is indexed idempotently in the dedicated
  `source_evidence` SQL table. The existing molecule-only `evidence` table is a
  separate molecule-observation table and is not the canonical source-evidence store.
- This indexing happens at the Extract/Detection join. Raw `extract.json` and
  `detection.json` remain unchanged; SQLite is the only runtime evidence read
  source after Join.
- If that SQL transaction fails, the raw branches and run checkpoint remain for
  a same-`run_id` retry; downstream stages are not started. No `bbox.json`
  snapshot is generated.

- Molecules, text–molecule links, report.json, per-page texts.
- DB target: **`{library_root}/.mbforge/library.db`** (unified). Previous
  `index/knowledge_base.db` and `index/molecules.db` layouts are not read by
  the current pipeline.
- If filesystem persistence fails after molecule rows are written, a
  compensation pass (`_compensate_molecule_persistence`) deletes the
  document-scoped molecule rows so the DB does not retain orphan data; a
  failure of the compensation itself is attached as the structured
  `compensation_failed` context flag on the `StageResult`.

#### Structure-role safety gate

Every normalized candidate is classified before persistence. `complete` is the
only role allowed into the concrete molecule library; `scaffold` and
`fragment` go to Markush storage, while `review_required` goes to the review
queue. Patent writes only activity-backed concrete candidates to the
`molecules` table; `confirm_complete` remains the review transition that can
write a manually confirmed candidate. `confirm_scaffold` and
`confirm_fragment` write only to `markush_scaffolds` / `markush_fragments`.

#### Markush review closure and enumeration gates

The review queue drives the only path from an unrecognized structure into the
concrete molecule library. The candidate detail response exposes stable
identity and eligibility fields: `scaffold_id`, `fragment_id`,
`enumeration_eligible`, and `enumeration_block_reasons` — derived from the
canonical Markush rows, never from a loose `properties.scaffold_id` fallback.

Enumeration is authorized entirely server-side. A selection is rejected with a
structured 422 before any generation run is created unless:

- the scaffold exists and is `confirmed`;
- every site belongs to that scaffold and is `confirmed`;
- every selected fragment exists, is `confirmed`, and is linked through a
  confirmed `markush_options` row or confirmed `markush_mounts` row;
- selection fragment identifiers match confirmed DB rows (client-provided
  SMILES are not trusted as identity).

Generated candidates always land in `markush_generated_candidates` with
`review_status='pending'`. A candidate may be confirmed or rejected only once,
while pending; `confirm` writes the molecule with a `markush_generation`
provenance block (generated id, run id, scaffold id, combination key,
assignments), and `reject` writes audit only. Rejected states are not revived
by re-import: the same `source_key` with the same `content_hash` preserves the
human decision, and a structurally changed re-occurrence supersedes the prior
row without restoring its old decisions. A closed SMILES does not override source evidence: Formula/R-group
context, synthesis-step labels such as `1a` or `21-e`, mixture/isomer wording,
and uncertain stereochemistry such as `Z/E` are all review signals. Bare final
labels such as `4A` or `4B` are not rejected by the label alone and still need
their local context to trigger review.

A step-like label (`1a`, `21-e`, `4A-1`, …) on its own is corpus-specific: on
a general corpus the same suffix appears in benign compound numbering, so the
label pattern alone is not enough to withhold a candidate. The synthetic
intermediate signal only fires when the candidate's surrounding context
contains a corroborating token — e.g. `Intermediate 1a`, `中间体 1a`,
`synthesis step 21-e`, `precursor`, `synthesized`. The full token list lives
in `INTERMEDIATE_CONTEXT_TOKENS` in
`src/mbforge/pipeline/classify_structure_role.py`. Without that context, the
candidate falls through to the normal final-label path and is treated like
`4A`/`4B` (i.e. eligible for `complete` once other gates pass).

---

## Final filesystem layout (canonical)

```
{library_root}/
├── storage/{doc_id}/
│   ├── source.pdf
│   ├── document.md
│   ├── report.json
│   ├── pages/page_NNNN.txt
│   ├── images/*.png              # cloud OCR extracted figures, when present
│   └── crops/*.png
├── .mbforge/
│   ├── library.db          # unified SQLite business data
│   ├── wiki/               # existing Wiki artifacts served by KB endpoints
│   └── migrations/         # archived legacy layouts
└── notes/                  # user notes
```

Path ownership:

- Library-level → `core/layout.py:LibraryLayout`
- Document-level → `core/artifact.py:ArtifactResolver`  
Do **not** join `storage/` / `.mbforge/` paths inline in new code.

---

## Failure cascade (summary)

| Failure | Typical impact |
|---|---|
| OCR exhausted | Empty pages → weak title → thin document metadata |
| MolDet / MolParser missing | `molecule_count=0`, no ESMILES evidence |
| Patent association ambiguity | Keep the fact and emit a structured review issue |

Pipeline is largely **best-effort across stages** with structured `StageResult`;
do not silently swallow errors without logging / pipeline events.

---

## Frontend consumption (representative)

| Endpoint area | Artifact |
|---|---|
| library document file / markdown / report / pages | `storage/{doc_id}/…` |
| persisted document activities and activity review matches | `GET /api/v1/activities/documents/{doc_id}` |
| crop serving | `storage/{doc_id}/crops/…` (legacy crops fallback) |
| KB search / wiki | Read-only access to existing SQLite FTS5/native Wiki data |
| moldet / coref APIs | live model path, not pipeline artifacts |

Query params and bodies use **`library_root` / `libraryRoot`** — not `project_root`.

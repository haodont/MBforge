# MBForge Project Analysis (2026-08-19)

Status: context snapshot for ongoing development. Recorded before the
decision to remove the agent module and Docker support (see
[`TODO/INDEX.md`](../../../TODO/INDEX.md) and the 2026-08-19 decision).

Status update (same day): the agent module and Docker removal described in
[`CHANGELOG.md`](../../../CHANGELOG.md) (`### Removed`) is now complete —
backend, frontend, tests, docs, and docs references have been verified
(`ruff check/format`, frontend lint/build/test, `pytest tests/ -q` with only
3 pre-existing `tests/eval` data-file failures).

## Overall judgment

MBForge is a local AI workbench for chemistry literature and patent PDFs.
The architecture is no longer a prototype: it has a complete chemistry
domain model, an extraction pipeline, an agent, and a frontend workbench.
It is best described as a *feature-rich local research baseline*, not a
production-reliable service.

Suggested investment order:

1. Task reliability (persistence, recovery, backpressure, GPU serialization)
2. Data consistency (delete-order fixes, audit orphans)
3. Real-sample acceptance (scanned PDFs, GPU models, browser, Docker-less startup)
4. Public API completeness (stub endpoints)
5. UI/UX polish

## Architecture at a glance

- Backend: Python 3.12 + FastAPI under `src/mbforge/`
  - `routers/` HTTP handlers, `models/` Pydantic schemas,
    `core/` business/storage, `pipeline/` seven-stage workflow,
    `backends/` model wrappers, `agent/` LangGraph agent,
    `chem/` RDKit helpers, `parsers/` document/molecule parsing,
    `utils/` config/logging/paths.
- Frontend: React 19 + TypeScript 6 + Vite under `frontend/src/`
  - `api/http/` REST/SSE clients, `api/query/` React Query hooks,
    `components/` UI, `context/` global state.
- Storage: single SQLite + FTS5 at `{library_root}/.mbforge/library.db`,
  WAL mode, per-thread connections.
- Chemistry: RDKit, MolDetv2-YOLO26 (`backends/moldet_v2_ft.py`),
  MolParser-Mobile E-SMILES (`molparser` package).
- Models: local-model routers mounted in the main app (the standalone
  `server.py` sidecar was removed on 2026-08-19).

## Seven-stage pipeline

Registered in `src/mbforge/pipeline/runner.py`; stages run sequentially in
one worker thread sharing `PipelineContext`:

1. `ExtractStage` — PyMuPDF text extraction, sparse pages via OCR chain.
2. `DensityStage` — page classified `text_only` / `mixed` / `image_only`.
3. `MarkdownStage` — coarse Markdown, MolDetv2 + MolParser detection,
   candidate normalization, MoleCode insertion.
4. `ReorganizeStage` — LLM chunked semantic reorganization; falls back to
   source Markdown; reuses cached `reorganized.md` by default.
5. `ActivityStage` — IC50/Ki/EC50/Kd extraction, preferring OCR-aligned
   enriched Markdown; reorganized Markdown is only a fallback.
6. `PersistStage` — classification complete/scaffold/fragment/review_required;
   writes molecule, activity, Markush, review, text links, reports.
7. `IndexStage` — SQLite FTS, heading tree, Wiki artifact.

Key characteristics:

- Stage errors are recoverable vs. fatal via `StageResult`; Activity/Index
  and some model/LLM failures degrade gracefully.
- Cancellation is cooperative checkpointing; in-flight model/remote requests
  cannot be force-killed.
- Staging images/crops in run-scoped dirs, promoted after all stages succeed.
- "Persist single txn" applies only to SQLite writes; file failures are
  compensated by best-effort rollback (not a true atomic DB+FS transaction).
- HTTP queue is in-process `_background_futures` on the default executor:
  no persistence, no recovery after restart, no global GPU concurrency cap.

## Strengths

1. Complete domain model: molecules, activities, Markush, review, KB, agent.
2. Clean layering: routers / core / pipeline / backends / chem.
3. Graceful degradation: OCR/LLM/molecule failures keep intermediate artifacts.
4. SQLite + FTS5 fits a local, portable research tool.
5. Decent test base: ~144 backend test files, 66 frontend test files,
   full text-only pipeline integration test (`tests/integration/test_pipeline_flow.py`),
   CI on Linux + Windows.
6. Mature docs governance: `docs/wiki` live, `docs/api` contracts,
   `plans` active designs, `archive` history.

## Known issues (priority order)

1. **In-process task execution model** (`routers/pipeline.py`): futures lost
   on restart, no cross-process mutex, no GPU serialization, no persistent
   queue; `worker/status` only reflects FastAPI liveness.
2. **Stub endpoints in the public API**: unused stub endpoints that returned
   fake-success defaults ("not implemented" was indistinguishable from "no
   data") were **removed** on 2026-08-19 (`pdf/classify|inspect|confirm-ocr|
   extract-text|parse|process-document|figure-bboxes`, `text/chunk`,
   `classify/page|document`, `extract/esmiles-candidates|associated-molecules`,
   `sar/find-scaffold|decompose`); live consumers and fail-closed SAR stubs
   remain.
3. **Docker frontend not reachable**: Dockerfile copies `frontend/dist` but
   `MBFORGE_SERVE_FRONTEND=1` is not set in the image; root path likely 404.
   (Note: Docker support was removed by the 2026-08-19 decision.)
4. **Duplicate sidecar/main assembly**: `server.py` and `app.py` each maintain
   model router prefix, lifespan, CORS, exception handling; version drift
   (1.2.0 vs 0.3.0). — **resolved on 2026-08-19**: the standalone
   `mbforge.server:app` sidecar was removed; the main app registers the same
   local-model routers (molparser/models/pdf-render) and holds the single
   lifespan (including the `MBFORGE_PREWARM_MODELS` gate), CORS, exception
   handlers, and version.
5. **Delete-order risks in `core/database.py`**: `markush_review_candidates`
   deleted before decisions queried via that table (audit orphans); molecule
   delete clears alias evidence via a molecules subquery that may be empty.
6. **Compatibility layers vs. dev-stage DB policy**: config migrations, old
   fields/endpoints, storage fallbacks, schema compat branches remain,
   widening the behavior matrix.
7. **Real-system acceptance gaps**: GPU models, cloud OCR/LLM, scanned PDFs,
   browser screenshots, Markush review→enumeration end-to-end are not in the
   stable quality gate (remaining P0/P1 work in `TODO/INDEX.md`).

## Notes from exploration

- Boundary leak: `pipeline/stages/markdown_stage.py` reuses `agent.llm_factory`
  for the cloud molecule fallback; a shared LLM factory should live in an
  infrastructure module rather than in the agent package.
- Docs drift: pipeline docs still contain old Popo descriptions; `IndexStage`
  file comment says "Stage 6".

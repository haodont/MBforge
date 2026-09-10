# Architecture And Engineering Rules

> Long-term reference for module boundaries, code style, paths, and
> configuration. Commands and contributor workflow are in
> [CONTRIBUTING.md](../../CONTRIBUTING.md). If this page conflicts with code,
> the code wins and this page must be updated.

## System shape

```text
React UI → HTTP clients / React Query → FastAPI routers
         → core / pipeline → model backends
         → SQLite FTS5 + native Wiki + library artifacts
```

| Area | Location | Rule |
|---|---|---|
| UI | `frontend/src/components/` | Components and page composition |
| HTTP client | `frontend/src/api/http/` | REST calls; server state uses React Query |
| API boundary | `src/mbforge/routers/` | Validation and orchestration only |
| Services | `src/mbforge/services/` | DB/IO use cases; the only layer that touches SQLite directly from the HTTP side. Grouped into domain subpackages: `molecule/`, `chem/`, `documents/`, `pipeline/`, `markush/`, `system/` |
| Core | `src/mbforge/core/` | Layout, database, artifacts, shared services |
| Business flow | `src/mbforge/pipeline/` | Stage-based PDF pipeline (stages self-register via `core/stage.py`) |
| Models | `src/mbforge/backends/` | Lazy-loaded OCR and molecular inference |

Router modules are grouped into domain subpackages: `system/` (health,
diagnostics, settings, resources, models, OCR probes), `documents/`
(library, documents, notes, pdf, activity), `molecule/` (molecule, chem,
sar, moldet, molparser), `pipeline/` (pipeline queue, detection cache),
plus `markush/` and top-level `review.py`. Routers must not import
`DatabaseManager` or `storage.sqlite` — queue, molecule, detection-cache,
review, markush, and readiness operations live in `services/`, and services
resolve their own database handles (routers pass `library_root` only; the
markush shared handle helper is `services/markush/_db.py`). Path/layout
helpers reach routers only through `routers/_path_utils.py`. Request bodies
must be typed Pydantic models, not raw `dict`s.

### Diagnostics, evidence, and review

- The runtime diagnostics endpoints are exposed under `/api/v1/diagnostics`;
  the Settings diagnostics tab consumes the summary, LLM probe, and demo-run
  operations without duplicating health-ring-buffer routes.
- Evidence and molecule location APIs expose 1-based pages. SQL explicitly
  converts the legacy `molecule_detections.page` 0-based value at the boundary;
  callers must not perform a second conversion.
- `molecule_corrections` is an append-only audit trail for user SMILES edits.
  `review_items` is the native review queue, while `services/review_queue.py`
  presents it together with Markush candidates and routes decisions to their
  owning persistence tables. Re-import upserts preserve an existing human
  decision status.
- `frontend/src/components/review/ReviewCenter.tsx` is mounted at `/review`
  and opens source documents through `AppContext` deep-link fields
  (`initialPage` and `initialBbox`).

Dependencies flow downward. Routers do not contain business logic; backends do
not call the UI or routers.

## Canonical paths and settings

- Python uses `library_root`; TypeScript and wire payloads use `libraryRoot`.
- `LibraryLayout` owns library-level paths.
- `ArtifactResolver` owns `{library_root}/storage/{doc_id}/` paths.
- The primary database is `{library_root}/.mbforge/library.db`.
- Native document search reads existing sections/chunks through
  `core/knowledge_index.py`; Wiki endpoints serve existing artifacts under
  `{library_root}/.mbforge/wiki/` plus SQLite FTS5 tables. Neither is a stage
  of the PDF ingestion pipeline.
- Business settings are read and written through `mbforge.utils.config` and
  stored in `~/MBForge/settings.json`.
- Do not introduce `project_root`, inline joins for `storage/` or `.mbforge/`,
  or a runtime `configs/` directory.

### Development-stage database lifecycle

MBForge does not yet promise in-place compatibility for persisted databases.
Local SQLite data is development data, and schema work targets a freshly
initialized database using the current canonical schema.

Until the project owner explicitly establishes a persistent-data compatibility
boundary, schema changes must update the current schema directly. Do not add
schema-version migrations, legacy-schema branches, dual-write compatibility,
historical database fixtures, or rollback migrations. Existing migration code
is historical and should not be extended; ask whether to remove or simplify it
when work enters that area.

Rebuilding a development database is the expected response to an incompatible
schema change, but agents must still obtain explicit approval before deleting
any local database file. Migration support becomes required only after an ADR
records the first compatibility-sensitive release or dataset.

## API and backend additions

1. Add a Pydantic request/response model at the API boundary.
2. Add an `APIRouter` under `src/mbforge/routers/` and register it with
   `include_router` in `app.py` using `/api/v1`.
3. Put blocking file/model work behind `asyncio.to_thread()` or an executor.
4. Route frontend calls through `frontend/src/api/http/`; add React Query hooks
   for server state.
5. Document public paths and behavior in [the API index](../api/README.md).

Expected failures use `MBForgeError` subclasses with an `error_code` and
context. Log through `get_logger(__name__)`; do not use `print`, bare
`except`, or silent error swallowing.

## Pipeline additions

The registry is `core/stage.py`. New stages must implement `StageExecutor`,
keep per-run state in `PipelineContext`, and emit through the existing
pipeline event channel. See
[pipeline.md](pipeline.md) for the current contract.

## Frontend conventions

- Components use `PascalCase`; hooks use `useCamelCase`.
- `DocumentViewer` hosts the PDF workbench; its comparison sidebar owns the
  document Markdown, Wiki, and current-page molecule views. MoleCode page links
  call the `PdfViewerHandle` so the PDF and Markdown remain aligned.
  See [`DocumentViewer.tsx`](../../frontend/src/components/project/DocumentViewer.tsx)
  and [`PdfViewer.tsx`](../../frontend/src/components/project/PdfViewer.tsx).
- OCR fallback order is persisted as `ocr.priority` in `settings.json` and
  consumed by `backends/ocr/chain.py`; omitted providers are appended in the
  default order so a partial setting cannot disable the fallback chain.
- `/api/v1/models/loaded-status` reports in-process MolDet/MolParser state and
  process RSS; `/api/v1/models/clear-cache` releases loaded model memory while
  retaining downloaded weight files.
- See [API index](../api/README.md) for the public diagnostics, molecule
  location/correction, and unified review routes.
- Python uses `snake_case`; public classes use `PascalCase`.
- Cross-directory TypeScript imports use `@/` and type-only imports use
  `import type`.
- Use `useState` for local UI state, `AppContext` for shared UI state, and
  React Query for server state.
- Python formatting/linting is Ruff with line length 88 and target `py312`;
  TypeScript uses the repository ESLint and strict TypeScript settings.

## Data and error contract

Pydantic and TypeScript fields must retain the same meaning. A normal API error
uses the shared envelope documented in [api/README.md](../api/README.md).
Configuration writes go through `save_global_config` or `update_settings`.

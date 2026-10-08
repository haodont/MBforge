# Backend architecture

MBForge follows a small layered backend: five layers, plus the neutral
`ports/` and `contracts/` packages and the `foundation/` support package.

| Layer | Responsibility | May depend on |
|---|---|---|
| `domain` | Molecular, evidence, review, and Markush rules | stdlib, `foundation` |
| `db` | SQLite/filesystem persistence and repository implementations | `ports`, `contracts`, `domain`, `foundation` |
| `service` | Use cases, pipeline orchestration, DTOs | `domain`, `foundation`, `ports`, `contracts` |
| `api/http` | FastAPI input validation and response mapping | `service`, `ports`, `contracts`, `foundation` |
| `server` | Runtime services (model/OCR lifecycle, processes, ingest queue/worker) and `app.py`, the composition root | `service`, `foundation` |

Two neutral packages sit below the layers so a lower layer never imports the
layer above it:

- `mbforge/ports/` owns the repository and runtime protocols
  (`repositories.py`, `runtime.py`, `pipeline.py`) and their install/lookup
  helpers. They moved out of `service` so the concrete `db` adapters implement
  them without importing `service`.
- `mbforge/contracts/` owns the cross-layer request/read models (molecule,
  Markush) that a `db` adapter or a port must reference. The owning `service`
  DTO modules re-export these names for their existing callers.

`foundation/` is the one cross-cutting support package — config, paths, errors,
logging, IDs, library layout, queue contract — plus the model inference backends
under `foundation/inference/` (MolDet, MolParser, Hiro-Layout, SLANet, RapidOCR).
It is imported by every layer but depends on none of them. `foundation/inference/assets.py`
defines the `ResourceResolver` protocol; the composition root injects the concrete
`ResourceManager` through it, so the inference backends no longer import `server`.

Use cases obtain persistence through `get_repositories(library_root)` and
runtime capabilities through `get_runtime()`. The concrete implementations
are installed once by `create_app()` and by the test composition root.

The repository set contains database, evidence, Markush, review, and artifact
stores. The runtime provider contains model lifecycle, MolDet, MolParser, OCR,
process, and ingest worker capabilities. This keeps HTTP and service modules
independent of SQLite and heavyweight model imports.

The chat LLM is outside this layering: the `agent/` Node sidecar owns every
provider call (chat, model list, connectivity probe). Python persists
`AppConfig.llm` in `settings.json`, which the sidecar reads, and readiness
reports only whether those settings are complete.

Paths have one authority: `LibraryLayout` for library and document paths, plus
the artifact store for document records and cached PDF text. The database remains
a single SQLite file at the library root.

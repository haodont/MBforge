# Backend architecture

MBForge follows a small layered backend: five layers plus one support package.

| Layer | Responsibility | May depend on |
|---|---|---|
| `domain` | Molecular, evidence, review, and Markush rules | stdlib, `foundation` |
| `db` | SQLite/filesystem persistence and repository implementations | `service` ports, `domain`, `foundation` |
| `service` | Use cases, pipeline orchestration, DTOs, ports | `domain`, `foundation`, ports |
| `api/http` | FastAPI input validation and response mapping | `service`, ports, `foundation` |
| `server` | Runtime services (model/OCR lifecycle, LLM, processes, ingest queue/worker) and `app.py`, the composition root | `service`, `foundation` |

`foundation/` is the one cross-cutting support package — config, paths, errors,
logging, IDs, library layout, queue contract — plus the model inference backends
under `foundation/inference/` (MolDet, MolParser, Hiro-Layout, SLANet, RapidOCR).
It is imported by every layer but depends on none of them.

Use cases obtain persistence through `get_repositories(library_root)` and
runtime capabilities through `get_runtime()`. The concrete implementations
are installed once by `create_app()` and by the test composition root.

The repository set contains database, evidence, Markush, review, and artifact
stores. The runtime provider contains model lifecycle, MolDet, MolParser, OCR,
LLM, process, and ingest worker capabilities. This keeps HTTP and service
modules independent of SQLite and heavyweight model imports.

Paths have one authority: `LibraryLayout` for library paths and the artifact
store for document records and cached PDF text. The database remains a single
SQLite file under `.mbforge`.

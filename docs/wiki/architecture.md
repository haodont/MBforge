# Backend architecture

MBForge follows a small layered backend:

| Layer | Responsibility | May depend on |
|---|---|---|
| `domain` | Molecular, evidence, review, and Markush rules | `foundation` and stdlib |
| `application` | Use cases, pipeline orchestration, DTOs, ports | `domain`, `foundation`, ports |
| `adapters` | SQLite, files, models, OCR, LLM, processes, queue worker | application contracts, domain, foundation |
| `interfaces/http` | FastAPI input validation and response mapping | application, ports, foundation |
| `app.py` | Concrete wiring and lifecycle | all runtime layers |

Use cases obtain persistence through `get_repositories(library_root)` and
runtime capabilities through `get_runtime()`. The concrete implementations
are installed once by `create_app()` and by the test composition root.

The repository set contains database, evidence, Markush, review, and artifact
stores. The runtime provider contains model lifecycle, MolDet, MolParser, OCR,
LLM, process, and ingest worker capabilities. This keeps HTTP and application
modules independent of SQLite and heavyweight model imports.

Paths have one authority: `LibraryLayout` for library paths and the artifact
store for document records and cached PDF text. The database remains a single
SQLite file under `.mbforge`.

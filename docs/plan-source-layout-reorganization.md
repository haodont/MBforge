# Source layout reorganization

Status: implemented on 2026-09-22.

The backend now exposes directory names that match responsibility and keeps the concrete database, filesystem, model, and process implementations behind application ports.

## Final structure

```text
src/mbforge/
├── app.py                         # composition root
├── domain/                        # pure business objects and rules
├── application/
│   ├── dto/                       # HTTP and use-case data contracts
│   ├── ports/                     # repository and runtime capabilities
│   ├── use_cases/                 # application workflows
│   └── pipeline/                  # stages, runner, artifacts, checkpoints
├── adapters/
│   ├── persistence/               # SQLite and filesystem implementations
│   ├── inference/                 # MolDet, MolParser, OCR, layout backends
│   └── runtime/                   # LLM, models, process, ingest worker
├── interfaces/http/               # FastAPI request/response boundary
└── foundation/                    # config, paths, errors, logging, IDs
```

`application/ports/repositories.py` owns the persistence contracts. The composition root installs `SqliteRepositories`; use cases resolve a repository set from `library_root` and do not import `DatabaseManager`, DAO modules, or document storage modules. `application/ports/runtime.py` applies the same rule to model, OCR, LLM, process, and queue capabilities.

The only runtime database is still `{library_root}/.mbforge/library.db`. `LibraryLayout` and the artifact store remain the path authorities. No database schema or API wire format changed in this reorganization.

## Dependency rules

- `domain` imports only standard-library and foundation primitives.
- `application` imports domain, foundation, DTOs, and ports; it does not import concrete adapters or HTTP interfaces.
- `interfaces/http` imports application use cases, DTOs, ports, and foundation; it does not open databases or call concrete model/persistence adapters.
- `adapters` implement ports and may depend on domain/application contracts; they do not depend on HTTP interfaces.
- `app.py` is the composition root and is the one place that wires concrete repository and runtime providers.

`tests/unit/architecture/test_layer_boundaries.py` checks the import rules as a small regression contract.

## Pipeline contract

The registered path is now `Extract → Join → Markdown → Patent`. Extract is the single producer (layout/text/table recognition plus the MolDet+MolParser molecule pass) and writes one run-scoped artifact; Join validates it and writes canonical `SourceEvidence` rows to SQLite. Link is removed from the active path and Persist remains an unregistered future redesign. The stage contract lives in `application/pipeline/stage.py`, while the terminal queue statuses live in `foundation/queue_contract.py` so both the application queue facade and the runtime worker use one definition.

## Verification

The migration was checked with Python 3.12 imports, bytecode compilation, the full backend suite (848 passed), Ruff, and Ruff formatting. Frontend tests (298 passed), lint, and production build also pass. Frontend dependency versions retain React 19 and Ketcher 3.18; the Node engine is pinned to `>=24.14.1` for that stack.

# Source layout reorganization

Status: implemented on 2026-09-22; reorganized on 2026-09-29 into five layers
(`domain / service / db / api / server`) plus one `foundation` support package.

The backend now exposes directory names that match responsibility and keeps the concrete database, filesystem, model, and process implementations behind service ports.

## Final structure

```text
src/mbforge/
├── domain/                        # pure business objects and rules
├── service/
│   ├── dto/                       # HTTP and use-case data contracts
│   ├── ports/                     # repository and runtime capabilities
│   ├── use_cases/                 # service workflows
│   └── pipeline/                  # stages, runner, artifacts, checkpoints
├── db/                            # SQLite and filesystem implementations
├── api/http/                      # FastAPI request/response boundary
├── server/                        # LLM, models, process, ingest worker + app.py (composition root)
└── foundation/                    # config, paths, errors, logging, IDs
    └── inference/                 # MolDet, MolParser, OCR, layout backends
```

`service/ports/repositories.py` owns the persistence contracts. The composition root installs `SqliteRepositories`; use cases resolve a repository set from `library_root` and do not import `DatabaseManager`, DAO modules, or document storage modules. `service/ports/runtime.py` applies the same rule to model, OCR, LLM, process, and queue capabilities.

The only runtime database is still `{library_root}/.mbforge/library.db`. `LibraryLayout` and the artifact store remain the path authorities. No database schema or API wire format changed in this reorganization.

## Dependency rules

- `domain` imports only standard-library and foundation primitives.
- `service` imports domain, foundation, DTOs, and ports; it does not import concrete db/runtime adapters or the HTTP api.
- `api/http` imports service use cases, DTOs, ports, and foundation; it does not open databases or call concrete model/persistence adapters.
- `db` implements ports and may depend on domain/service contracts; it does not depend on the HTTP api or the server runtime.
- `server/app.py` is the composition root and is the one place that wires concrete repository and runtime providers.
- `foundation` is the shared support package (config, paths, errors, logging, IDs, plus the `foundation/inference` model backends); it depends on none of the business layers.

`tests/unit/architecture/test_layer_boundaries.py` checks the import rules as a small regression contract.

## Pipeline contract

The registered path is now `Extract → Markdown → Patent`. Extract is the single producer (layout/text/table recognition plus the MolDet+MolParser molecule pass) and mints and persists the canonical `SourceEvidence` rows to SQLite itself — SQL is the only evidence store, with no branch artifact; Markdown assembles the readable document from that evidence and Patent publishes the unified facts. Link and Persist are removed from the active path. The stage contract lives in `service/pipeline/stage.py`, while the terminal queue statuses live in `foundation/queue_contract.py` so both the service queue facade and the runtime worker use one definition.

## Verification

The migration was checked with Python 3.12 imports, bytecode compilation, the full backend suite (848 passed), Ruff, and Ruff formatting. Frontend tests (298 passed), lint, and production build also pass. Frontend dependency versions retain React 19 and Ketcher 3.18; the Node engine is pinned to `>=24.14.1` for that stack.

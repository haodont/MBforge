# Repository Guidelines
MBForge is a local AI workbench that turns molecular-science PDFs into a searchable knowledge base. The current pipeline is `Extract → Markdown → Patent`; Extract runs the layout/text/table producer and the molecule (MolDet + MolParser) pass and mints and persists the canonical SQL `SourceEvidence` rows itself, Markdown assembles the readable document from that evidence, and Patent reads it, publishes the unified facts artifact, and performs deterministic document-local associations. SQL is the only evidence store — there is no branch artifact. Link and Persist are removed from the active path. Read `TODO/INDEX.md` before changing pipeline, storage, or APIs.

## rule to design a test
- mark accossiated function at top of test_file
- function and type restrict is more import than a lot of test
- always try to use a bigger usage test instead of several mini-single test
- try to reuse test alreday exist 

## Project Structure & Architecture

- `src/mbforge/`: FastAPI backend, organized as five layers plus one support package. `domain/` owns pure business types and rules; `service/` owns DTOs, use cases, pipeline orchestration, ports, and the agent-callable capability registry (`service/capabilities/`); `db/` owns SQLite/filesystem persistence; `api/http/` validates HTTP requests and delegates; `server/` owns runtime services (process governance, ingest queue/worker, model/resource management) and `server/app.py` is the composition root; `foundation/` is the shared support package (config, paths, errors, logging, small runtime contracts) with the model inference backends under `foundation/inference/`.
- `agent/`: Pi 1.5 CLI extension — the only agent entry point; there is no HTTP agent server. `extension.ts` registers backend capabilities as pi tools and `capabilities.ts` loads the manifest; one session mode (`auto` default, `dev`) controls capability depth and built-in repository tools, `/mbforge mode auto|dev` switches it in-session, and the model may call `request_dev_mode`, which only opens a confirmation dialog — an approved request switches the session like the command, and the launcher starts the FastAPI backend when nothing is listening. Assistant replies link into the workbench through program-rendered `[[ui:…]]` markers (review center, one review item, document page, queue) and `[[ev:…]]` evidence citations; the model never authors a URL, because the frontend address and encoding come from the CLI. There is no read-only session mode: the capability token is the write gate for capability calls, so a session without a readable token file keeps every read tool and gets 403 on mutating capabilities. That gate does not cover the unauthenticated frontend routes under `/api/v1/*` — a browser running as the same user cannot hold a secret the agent cannot read — so `dev` mode is a human trust boundary, not a sandbox, and the prompt forbids using its built-in tools to call the API or open `library.db`. Capability results that carry a `run_id` are watched by the extension: a terminal run is reported once, delivered only when the session is idle (held in memory while busy, never through pi's queued `deliverAs` path), so resuming a session does not replay old completions.
- `frontend/src/`: React and TypeScript UI. Keep REST clients in `api/http/`, React Query hooks in `api/query/`, and components in `components/`.
- Frontend UI must reuse the existing component library (`components/ui`) for panels, tabs, buttons, badges, loading, and collapse behavior. Before creating a new interaction or visual primitive, check the library and prefer composition; do not reimplement an existing component's behavior locally.
- Patent facts reads must use the shared committed-snapshot use case, including the HTTP document endpoint. Projection status is observed on read and excluded from stored payloads; evidence-tool coverage records actual returns and truncation, not semantic verification. The Patent stage is deterministic: the optional LLM-led Patent analysis, its gap tools and the research/review-assistant surfaces that carried them are removed.
- Agent-callable capabilities live in `service/capabilities/` and are exposed at `/api/v1/capabilities` (manifest, guide, invoke). Read-only calls need no credential; mutating calls require `X-MBForge-Token` from `{library_root}/.mbforge/capability-token`. The HTTP adapter only resolves the active library and serializes; mode checks and handlers stay in the registry. `agent/src/extension.ts` turns the manifest into pi CLI tools. `import_pdf` registers a library-local path and, unless `ingest.auto_enqueue_on_import` is disabled, queues Extract → Markdown itself.
- The read-only `get_api_surface` capability reports the live HTTP routes and their request-model fields (types, required flags, defaults, aliases, constraints); call it instead of guessing a route or payload.
- `tests/unit/`: backend tests; frontend tests are colocated as `*.test.ts` or `*.test.tsx`. Long-term documentation belongs in `docs/`.

Dependencies flow downward `api → service → db`; `service`/`db`/`api` may use the `foundation` support package but never a layer above them. `domain/` must not import service, db, api, or server; `service/` must use ports instead of concrete db/runtime adapters; `api/` must use service use cases and ports; `server/app.py` wires the concrete repository/runtime providers. Request bodies must be typed Pydantic models, not raw `dict`s. Use `LibraryLayout` for library and document paths. The database is `{library_root}/library.db`; artifacts are under `{library_root}/storage/{doc_id}/`. `library_root` defaults to `<source_root>/library`, which is also the app data directory for settings, logs and model weights. Document records live in the `documents` table (doc_id = SHA-256 hex of the file bytes, `file_name` unique); the stored PDF sits at `storage/{doc_id}/{file_name}`. Human-facing surfaces show the 12-character `short_id` (any unique 8+ hex prefix still resolves); the full id remains the stored key.

## Model & OCR Backends

- Molecule recognition is two-model: MolDetv2-FT (YOLO26, `foundation/inference/moldet_v2_ft.py`) detects structure bboxes on fitz-rendered PDF pages; MolParser-Mobile (`foundation/inference/molparser.py`) turns each crop into Layer-1 SMILES + Layer-2 E-SMILES (`SMILES<sep>EXTENSION`, trailing bare `<sep>` must be stripped). RapidOCR (`foundation/inference/ocr/crop_labels.py`) only reads compound-number labels off crop offcuts — enrichment only, silently empty on failure; never let it fail extraction.
- Page layout and page text are **local-only**: the Extract branch runs Hiro-Layout (`foundation/inference/hiro_layout.py`) on a 144 DPI render, merges/orders its regions, and reads text with the local RapidOCR reader (`foundation/inference/ocr/page_text.py`). There is no cloud OCR provider, no OCR fallback chain, and no `AppConfig.ocr` — never reintroduce one. Configure the branch via `AppConfig.layout`.
- Model weights resolve through `ResourceManager`, whose cache directory (`library/models`, overridable via `model_cache_dir`) is the only download target and the only read source. Downloads are ModelScope-first with a HuggingFace fallback; the SDK path verifies its snapshot and falls back to direct HTTP when it writes nothing. Each backend loads its model **once per process** into a singleton reused by every task, and a failed load is cooled down (`foundation/inference/load_guard.py`) instead of retried per crop. Tests must not require model weights or network.
- The chat LLM has no Python client. `server/llm/` was removed: the pi CLI (`agent/`) owns every provider call and keeps provider login, model choice and sessions in the isolated project agent directory `agent/.pi-agent/` (`PI_CODING_AGENT_DIR`), which is git-ignored and never merged with `~/.pi/agent`. Python only persists `AppConfig.llm` and reports its completeness in readiness — never add a Python chat client, provider default table, model list, or provider probe back.
- `TODO/INDEX.md` records the current pipeline facts, known inconsistencies, and pending work.

## Build, Test, and Development Commands

Use Python 3.12, `uv`, Node 24.14.1+, and npm:

```bash
uv sync
npm --prefix frontend install
npm --prefix agent install
npm --prefix frontend run dev:all
npm --prefix agent run cli
uv run pytest tests/ -q
uv run ruff check src tests
uv run ruff format src tests --check
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

The combined dev command runs backend reload and Vite HMR only. The agent CLI is a separate foreground process started with `npm --prefix agent run cli`; it starts the backend itself when none is running and stops only the backend it started. Stop verification servers; defaults are ports 18792 and 5173.

## Coding Style & Naming Conventions

Python uses four spaces, Ruff formatting, type hints, `snake_case`, and `PascalCase` classes. Log with `get_logger(__name__)`; use typed `MBForgeError` API errors and avoid `print()` or bare `except`. Use MolParser E-SMILES for molecule recognition. TypeScript is strict: use `PascalCase` components, `useCamelCase` hooks, `@/` imports, and `import type`.

## Testing Guidelines

Test count and coverage percentage are not goals. Every new or expanded test MUST pass this admission gate:

1. Name the concrete regression or externally observable contract it protects.
2. Show that the behavior is not already protected by an existing test.
3. Choose the lowest single layer that can prove it without asserting implementation details.

If any answer is missing, do not add the test. Tests are allowed only for a reproduced bug; a public API, storage, pipeline, or cross-module contract; a critical user workflow; or a non-trivial branch/error boundary where failure could silently corrupt data, return a materially wrong result, or bypass security/error handling.

Tests MUST NOT cover pass-through wrappers, getters/setters, constants, type declarations, static defaults, framework/library behavior, mock call sequences without an outcome assertion, private helpers already covered through a public boundary, cosmetic markup/copy/CSS, equivalent input permutations, or the same contract at unit, integration, and UI layers. Do not add tests solely because code is new, a branch exists, or coverage decreases.

Default to one behavior, one test, at one layer. Extend the nearest existing test before creating a file; create a test file only for a new contract with no suitable home. Parameterize only genuinely distinct boundaries. A behavior-preserving refactor adds no tests. When changing an area, consolidate or remove tests that duplicate stronger coverage or break on internal refactors while behavior is unchanged; do not perform unrelated mass deletion.

Name focused tests `test_<behavior>_<scenario>`. Prefer `tmp_path` and the minimum real schema needed by the contract; add legacy-schema cases only when compatibility is itself an approved contract. Run the smallest affected test set while iterating and report the exact verification scope. Run full backend and frontend suites only for shared infrastructure, cross-module/public-contract changes, release validation, or when explicitly requested.

## Commit & Pull Request Guidelines

Use Conventional Commits, such as `refactor(pipeline): simplify stage flow`. Keep one logical change per commit and stage only related paths. PRs should include scope, linked Issue/TODO, verification, risks/rollback, and screenshots for UI changes.

## Security & Configuration

Never add secrets, PDFs, logs, runtime library data, or unapproved model weights. Read global settings through `mbforge.foundation.config`; use `library_root` in Python and `libraryRoot` in TypeScript. Local SQLite is disposable development data: update the canonical schema directly and add migrations only after an owner-approved ADR establishes compatibility requirements.

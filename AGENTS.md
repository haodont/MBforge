# Repository Guidelines
function and type restrict is more import than a lot of test!!!
more structure less test!!!
MBForge is a local AI workbench that turns molecular-science PDFs into a searchable knowledge base. The current pipeline is `Extract ∥ Detection → Markdown → Patent`; Patent reads SQL `SourceEvidence`, publishes the unified facts artifact, and performs deterministic document-local associations. Link is removed from the active path; Persist remains unregistered for a later redesign. Read `TODO/INDEX.md` before changing pipeline, storage, or APIs.

## Project Structure & Architecture

- `src/mbforge/`: FastAPI backend. Routers (grouped into `system/`, `documents/`, `molecule/`, `pipeline/`, `markush/` subpackages) validate and delegate; `services/` (subpackageed by domain: `molecule/`, `chem/`, `documents/`, `pipeline/`, `markush/`, `system/`) owns DB/IO use cases; `core/` owns pure domain logic and the stage contract (`core/stage.py`); `pipeline/` owns stage implementations; `backends/` wraps models; `infra/` owns process governance and the ingest executor (`infra/ingest/`).
- `frontend/src/`: React and TypeScript UI. Keep REST clients in `api/http/`, React Query hooks in `api/query/`, and components in `components/`.
- Frontend UI must reuse the existing component library (`components/ui`) for panels, tabs, buttons, badges, loading, and collapse behavior. Before creating a new interaction or visual primitive, check the library and prefer composition; do not reimplement an existing component's behavior locally.
- `tests/unit/` and `tests/integration/`: backend tests; frontend tests are colocated as `*.test.ts` or `*.test.tsx`. Long-term documentation belongs in `docs/`.

Dependencies flow downward from UI to HTTP/Query, routers, services, core/pipeline, backends, and storage. Routers must not import `DatabaseManager` directly — put DB access in `services/` (services resolve their own handles; routers pass `library_root` only). Routers must not import `storage.layout` or `storage.sqlite` directly — go through `routers/_path_utils.py` or a service. Request bodies must be typed Pydantic models, not raw `dict`s. Use `LibraryLayout` for library paths and `ArtifactResolver` for document paths. The database is `{library_root}/.mbforge/library.db`; artifacts are under `{library_root}/storage/{doc_id}/`.

## Model & OCR Backends

- Molecule recognition is two-model: MolDetv2-FT (YOLO26, `backends/moldet_v2_ft.py`) detects structure bboxes on fitz-rendered PDF pages; MolParser-Mobile (`backends/molparser.py`) turns each crop into Layer-1 SMILES + Layer-2 E-SMILES (`SMILES<sep>EXTENSION`, trailing bare `<sep>` must be stripped). RapidOCR (`backends/ocr/crop_labels.py`) only reads compound-number labels off crop offcuts — enrichment only, silently empty on failure; never let it fail extraction.
- Scanned-page OCR is cloud-only: PaddleOCR is the sole backend (MinerU/GLM-OCR removed 2026-09-07, no compat). Configure via `AppConfig.ocr`.
- Model weights load lazily via `ResourceManager.ensure("moldet"/"molparser")` (auto-pull from ModelScope on first use). Tests must not require model weights or network. GPU inference is wrapped in `infra/process.gpu_gate()`.
- `docs/wiki/pipeline.md` is the canonical per-stage contract; `TODO/INDEX.md` records known inconsistencies and pending work.

## Build, Test, and Development Commands

Use Python 3.12, `uv`, Node 20.19+, and npm:

```bash
uv sync
npm --prefix frontend install
npm --prefix frontend run dev:all
uv run pytest tests/ -q
uv run ruff check src tests
uv run ruff format src tests --check
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

The combined dev command runs backend reload and Vite HMR. Stop verification servers; defaults are ports 18792 and 5173.

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

Use Conventional Commits, such as `refactor(pipeline): simplify stage flow`. Keep one logical change per commit and stage only related paths. PRs should include scope, linked Issue/TODO, verification, risks/rollback, screenshots for UI changes, and docs/`CHANGELOG.md` updates for user-visible behavior.

## Security & Configuration

Never add secrets, PDFs, logs, runtime library data, or unapproved model weights. Read global settings through `mbforge.utils.config`; use `library_root` in Python and `libraryRoot` in TypeScript. Local SQLite is disposable development data: update the canonical schema directly and add migrations only after an owner-approved ADR establishes compatibility requirements.

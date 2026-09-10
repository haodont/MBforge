# Fix Global Code Review Issues — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Each task is a focused bugfix cluster; exact code changes require reading the relevant files first.

**Goal:** Fix the Critical and Important issues identified in `docs/reviews/global-code-review-2026-07-13.md`, layer by layer, with tests and reviews at each step.

**Architecture:** Keep changes minimal and scoped. Prefer fixing the reported issue over opportunistic refactors. Reuse existing helpers (`ArtifactResolver`, `LibraryLayout`, `MBForgeError` subclasses, `get_logger`). Add or update tests so the bug cannot regress.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, pytest, Ruff; TypeScript 6, React 19, Vite 8, vitest.

## Global Constraints

- Python target version: 3.12 (`requires-python = ">=3.12"` in `pyproject.toml`).
- Ruff target-version must be updated to `py312` during this campaign.
- All module loggers must come from `mbforge.utils.logger.get_logger(__name__)`.
- All filesystem paths must go through `ArtifactResolver` / `LibraryLayout`; direct `Path` construction from request input is prohibited.
- All API boundaries must use Pydantic models, not raw `dict`.
- All async routes/handlers must avoid sync blocking I/O; use `loop.run_in_executor(None, ...)` or equivalent.
- `MBForgeError` subclasses must set `status_code` and `error_code`; central handler in `app.py` is the single source of error JSON.
- `os.environ` must not be used to pass API keys / SSL config at runtime.
- Tests must not mutate global module state directly; use `monkeypatch`.
- Commit after every task. Commit message follows repo convention: `fix(scope): description`.
- Do not occupy ports 18792 or 5173 for test servers.

---

## Layer 1 — Security & Core Correctness (Critical)

**Goal:** Eliminate path traversal, fix coref label mapping, restore OCR fallback, harden upload handling, unify error contracts.

### Task 1.1: Harden path handling in routers

**Issues:** C1 (path traversal in moldet_api, pdf, coref, detection_cache, library), C8 (upload filename traversal), C17 (tests accept absolute paths).

**Files:**
- Modify: `src/mbforge/routers/moldet_api.py` (lines ~209-211, ~335-359)
- Modify: `src/mbforge/routers/pdf.py` (line ~137)
- Modify: `src/mbforge/routers/coref.py` (lines ~141-170, ~337-338)
- Modify: `src/mbforge/routers/detection_cache.py` (line ~12)
- Modify: `src/mbforge/routers/library.py` (lines ~152, ~158-162)
- Modify: `src/mbforge/core/library.py` (lines ~153-172, ~199-221, ~255-275)
- Modify: `tests/unit/routers/test_pdf.py`, `tests/unit/test_routers_smoke.py`
- Create: `tests/unit/routers/test_path_traversal.py`

**Interfaces:**
- Consumes: `ArtifactResolver.source_pdf(doc_id)`, `LibraryLayout.for_root(root).storage`, `MBForgeError` subclasses.
- Produces: A helper `resolve_pdf_path(doc_id, library_root)` that returns an `ArtifactResolver` path or raises `MBForgeError(status_code=400/404, error_code="invalid_path"/"not_found")`.

**Steps:**
- [ ] **Step 1: Read current path handling in the listed routers and `ArtifactResolver`/`LibraryLayout`.**
- [ ] **Step 2: Add a private helper in `src/mbforge/routers/_path_utils.py` (or nearest shared module) that validates `library_root` via `LibraryLayout.for_root()` and resolves `doc_id` to `ArtifactResolver` paths, rejecting any request containing absolute paths, `..`, or path separators in `filename`.**
- [ ] **Step 3: Replace raw `Path(pdf_path)` / `Path(library_root)` usage in routers with the helper.**
- [ ] **Step 4: Sanitize upload `filename` in `library.py` using `Path(filename).name` and reject strings containing `/`, `\\`, or `..`.**
- [ ] **Step 5: Add tests that assert absolute `pdf_path`, `..`, and traversal filenames return 400/422/404 (not 200).**
- [ ] **Step 6: Run `uv run pytest tests/unit/routers/ -v` and `uv run ruff check src/mbforge/routers`.**
- [ ] **Step 7: Commit.**

### Task 1.2: Fix coref label mapping in moldet_api

**Issues:** C2 (wrong coref index), I27 (threshold inconsistency), I29 (stale comments).

**Files:**
- Modify: `src/mbforge/routers/moldet_api.py` (lines ~285-316)
- Modify: `src/mbforge/parsers/molecule/coref_alt.py` (pairing logic, comments)
- Modify: `tests/unit/routers/test_moldet_api.py` if exists, else create it.

**Interfaces:**
- Consumes: `CorefResult` dataclass, `coref_alt._pair_corefs`.
- Produces: Correct `label` field per molecule box and real `scribe_conf`.

**Steps:**
- [ ] **Step 1: Read the coref pairing and label assignment code in `moldet_api.py` and `coref_alt.py`.**
- [ ] **Step 2: Track the original `bboxes` index when filtering molecule boxes; use that index (not filtered list index) for `coref_label_map.get()`.**
- [ ] **Step 3: Where identifier bboxes are created with empty text, OCR the identifier crop via RapidOCR adapter or propagate existing text if available.**
- [ ] **Step 4: Return real MolScribe confidence instead of hard-coded `0.0`.**
- [ ] **Step 5: Reconcile `conf` threshold between `moldet_v2_ft.py` default (0.5) and downstream `mol_conf_threshold` (0.3) — make the router threshold the configurable gate or document the difference.**
- [ ] **Step 6: Update stale docstrings/comments in `coref_alt.py`.**
- [ ] **Step 7: Add/update unit tests asserting correct label mapping for mixed molecule/identifier ordering.**
- [ ] **Step 8: Run `uv run pytest tests/unit/routers/test_moldet_api.py tests/unit/parsers/ -v`.**
- [ ] **Step 9: Commit.**

### Task 1.3: Restore OCR fallback chain and fix IndexError

**Issues:** C3 (RapidOCR page fallback missing, `IndexError` in `_ocr_pages`), I18 (MinerU SSL/ZIP), C14 (sync httpx in OCR router).

**Files:**
- Modify: `src/mbforge/backends/ocr/local.py` (line ~34)
- Modify: `src/mbforge/backends/ocr/rapidocr_adapter.py` (DML detection, batching)
- Modify: `src/mbforge/pipeline/extract_text.py` (lines ~195-221)
- Modify: `src/mbforge/backends/ocr/mineru.py` (SSL env, ZIP handling)
- Modify: `src/mbforge/routers/ocr.py` (sync `httpx.Client` → `AsyncClient`)
- Create/Update: `tests/unit/backends/test_ocr_chain.py`, `tests/unit/pipeline/test_extract_text.py`

**Interfaces:**
- Consumes: OCR backend registry, RapidOCR adapter.
- Produces: Working local OCR fallback, async OCR status endpoints.

**Steps:**
- [ ] **Step 1: Read the OCR chain, `local.py`, `rapidocr_adapter.py`, and `extract_text.py`.**
- [ ] **Step 2: Replace the broken `get_rapid_ocr` import with the correct RapidOCR page-level adapter call.**
- [ ] **Step 3: Make `use_dml` configurable or auto-detect DirectML availability in `rapidocr_adapter.py`.**
- [ ] **Step 4: Fix `_ocr_pages` result list indexing so non-consecutive `page_indices` do not trigger `IndexError`.**
- [ ] **Step 5: Replace `os.environ["SSL_CERT_FILE"]` in `mineru.py` with `verify=certifi.where()` passed to httpx; add size/entry limits to ZIP download.**
- [ ] **Step 6: Convert `routers/ocr.py` outbound probes to `httpx.AsyncClient`.**
- [ ] **Step 7: Add tests for OCR fallback and non-consecutive page OCR.**
- [ ] **Step 8: Run `uv run pytest tests/unit/backends tests/unit/pipeline/test_extract_text.py -v`.**
- [ ] **Step 9: Commit.**

### Task 1.4: Unify error contracts and HTTP status codes

**Issues:** C15 (inconsistent error handling), C16 (wrong status codes in LibraryStore).

**Files:**
- Modify: `src/mbforge/routers/documents.py`, `src/mbforge/routers/library.py`, `src/mbforge/routers/molecule.py`
- Modify: `src/mbforge/core/library.py` (not-found paths)
- Modify: `src/mbforge/utils/helpers.py` (add `NotFoundError` subclass if missing)
- Update: `tests/unit/routers/*`

**Interfaces:**
- Consumes: `MBForgeError` hierarchy.
- Produces: Consistent `{success, error, error_code, severity, category}` responses from `app.py` handler only.

**Steps:**
- [ ] **Step 1: Audit routers that catch `MBForgeError` and return HTTP 200 with `{"success": false}`; replace with `raise` so `app.py` handles it.**
- [ ] **Step 2: Add/ensure `NotFoundError` has `status_code=404` and `error_code="not_found"`.**
- [ ] **Step 3: Update `LibraryStore` lookup failures to raise the appropriate `MBForgeError` subclass with correct status code.**
- [ ] **Step 4: Update tests to assert on `error_code` and HTTP status rather than raw `success:false` 200.**
- [ ] **Step 5: Run `uv run pytest tests/unit/routers -v`.**
- [ ] **Step 6: Commit.**

---

## Layer 2 — Concurrency & Global State (Critical)

**Goal:** Remove event-loop blocking, protect singleton loads, stop mutating `os.environ`.

### Task 2.1: Move sync work off the async event loop

**Issues:** C4 (blocking I/O/CPU in async routes/stages), I12 (IndexStage ThreadPoolExecutor per call), I17 (molscribe predict_batch not batched).

**Files:**
- Modify: `src/mbforge/pipeline/extract_text.py`, `src/mbforge/pipeline/extract_molecules.py`, `src/mbforge/pipeline/organizer.py`, `src/mbforge/pipeline/extract_activities.py`
- Modify: `src/mbforge/routers/chem.py`, `src/mbforge/routers/render.py`, `src/mbforge/routers/models_router.py`, `src/mbforge/routers/pipeline.py`
- Modify: `src/mbforge/agent/tools.py` (RDKit)
- Modify: `src/mbforge/pipeline/stages/index_stage.py`
- Modify: `src/mbforge/backends/molscribe.py`

**Interfaces:**
- Consumes: `asyncio` event loop, shared thread pool.
- Produces: Async wrappers for sync operations.

**Steps:**
- [ ] **Step 1: Identify sync calls in async contexts (PyMuPDF, PIL/NumPy, MolScribe, RDKit, LLM `invoke`, `time.sleep`).**
- [ ] **Step 2: Introduce or reuse a module-level/shared `ThreadPoolExecutor` (or `asyncio.to_thread`) and wrap blocking calls.**
- [ ] **Step 3: Replace per-call `ThreadPoolExecutor` in `IndexStage` with shared executor or `to_thread`.**
- [ ] **Step 4: Implement true batching in `molscribe.predict_batch` by collecting all crops and calling backend batch predict once.**
- [ ] **Step 5: Add async tests or use existing async fixtures to verify handlers don't block.**
- [ ] **Step 6: Run `uv run pytest tests/unit/routers tests/unit/pipeline -v`.**
- [ ] **Step 7: Commit.**

### Task 2.2: Stop mutating global `os.environ`

**Issues:** C5 (`OPENAI_API_KEY`, `OPENAI_API_BASE`, `SSL_CERT_FILE` writes in organizer/openkb/mineru).

**Files:**
- Modify: `src/mbforge/pipeline/organizer.py`
- Modify: `src/mbforge/openkb/indexer.py`, `src/mbforge/openkb/compiler.py`, `src/mbforge/openkb/query.py`
- Modify: `src/mbforge/backends/ocr/mineru.py`

**Interfaces:**
- Consumes: `AppConfig` via `load_global_config()`.
- Produces: Explicit `api_key`/`base_url`/`verify` arguments to litellm/httpx calls.

**Steps:**
- [ ] **Step 1: Locate every `os.environ[...] = ...` assignment in the listed files.**
- [ ] **Step 2: Replace with explicit kwargs to the downstream client (litellm, httpx, etc.).**
- [ ] **Step 3: Ensure `load_global_config()` is read once per call and values are passed through.**
- [ ] **Step 4: Add tests or mocks asserting no `os.environ` mutation during calls.**
- [ ] **Step 5: Run `uv run pytest tests/unit/pipeline tests/unit/openkb -v`.**
- [ ] **Step 6: Commit.**

### Task 2.3: Protect singleton model/agent loading with locks

**Issues:** C9 (race in moldet_v2_ft, molscribe, coref_alt, agent).

**Files:**
- Modify: `src/mbforge/backends/moldet_v2_ft.py`
- Modify: `src/mbforge/backends/molscribe.py`
- Modify: `src/mbforge/parsers/molecule/coref_alt.py`
- Modify: `src/mbforge/routers/agent.py`

**Interfaces:**
- Consumes: `threading.Lock` / `asyncio.Lock`.
- Produces: Thread-safe lazy model loading.

**Steps:**
- [ ] **Step 1: Read each singleton loading function.**
- [ ] **Step 2: Add a module-level lock and double-checked locking pattern for model/agent initialization.**
- [ ] **Step 3: Add a test that simulates concurrent first calls and verifies only one instance is created (mock the heavy constructor).**
- [ ] **Step 4: Run `uv run pytest tests/unit/backends tests/unit/agent tests/unit/parsers -v`.**
- [ ] **Step 5: Commit.**

---

## Layer 3 — Agent & Frontend Critical

**Goal:** Make Agent usable, fix frontend HTTP bridge, remove hardcoded URLs.

### Task 3.1: Make Agent tools aware of library_root and async-safe

**Issues:** C7 (tools hardcode `library_root=""`, molecule_search creates new event loop), I19 (ollama key, timeout, SSE error events).

**Files:**
- Modify: `src/mbforge/agent/tools.py`
- Modify: `src/mbforge/agent/graph.py`
- Modify: `src/mbforge/agent/llm_factory.py`
- Modify: `src/mbforge/routers/agent.py`
- Update: `tests/unit/agent/`

**Interfaces:**
- Consumes: `LibraryLayout`, `ArtifactResolver`, `PipelineContext`/graph `configurable`.
- Produces: Async tools that receive `library_root` from graph config; correct LLM kwargs.

**Steps:**
- [ ] **Step 1: Read current agent tools, graph config, router.**
- [ ] **Step 2: Pass `library_root` via LangGraph `configurable` and read it in tools.**
- [ ] **Step 3: Convert tools to async or use `run_sync` correctly; remove `new_event_loop()` + `run_until_complete()` anti-pattern.**
- [ ] **Step 4: Fix LLM factory: ollama should not require API key; pass `request_timeout` to LangChain; handle errors as SSE `error` events.**
- [ ] **Step 5: Add/update agent unit tests.**
- [ ] **Step 6: Run `uv run pytest tests/unit/agent -v`.**
- [ ] **Step 7: Commit.**

### Task 3.2: Fix frontend HTTP bridge and hardcoded URLs

**Issues:** C10 (hardcoded `127.0.0.1:18792`), C18 (`API_BASE=''`, unconditional JSON Content-Type, `libraryRoot` field, `importDocument` bypasses httpFetch), I20 (SSE abort/backoff, download cancel, blind cast), I21 (state/polling issues).

**Files:**
- Modify: `frontend/src/api/http/_utils.ts`
- Modify: `frontend/src/api/http/agent.ts`
- Modify: `frontend/src/api/http/sse.ts`
- Modify: `frontend/src/api/http/download.ts`
- Modify: `frontend/src/api/http/notes.ts`
- Modify: `frontend/src/api/http/library.ts`
- Modify: `frontend/src/hooks/useErrorReport.ts`
- Modify: `frontend/src/components/project/pdf/usePdfViewer.ts`
- Modify: `frontend/src/components/discover/ChatTab.tsx`
- Modify: `frontend/src/context/AppContext.tsx`, `frontend/src/App.tsx`
- Update: frontend tests

**Interfaces:**
- Consumes: Vite env / relative API paths.
- Produces: `API_BASE = '/api/v1'` default; conditional Content-Type; abortable SSE; backend-sourced `libraryRoot`.

**Steps:**
- [ ] **Step 1: Read all listed frontend HTTP/state files.**
- [ ] **Step 2: Replace hardcoded `http://127.0.0.1:18792` with relative `/api/v1` or configurable `import.meta.env.VITE_API_BASE`.**
- [ ] **Step 3: Make `httpFetch` set `Content-Type: application/json` only when body is a string and no explicit header is provided; support FormData/ArrayBuffer.**
- [ ] **Step 4: Rename `libraryRoot` request fields to `library_root` everywhere; update types.**
- [ ] **Step 5: Route `importDocument` through `httpFetch` and check `resp.ok`.**
- [ ] **Step 6: Add AbortController support to `fetchSSE`; reset backoff on successful reconnect; allow cancellation in `downloadModel`.**
- [ ] **Step 7: Make backend settings the single source of truth for `libraryRoot`; remove competing `localStorage` source or reconcile it on mount.**
- [ ] **Step 8: Update frontend tests and run `cd frontend && npx tsc --noEmit && npm run test`.**
- [ ] **Step 9: Commit.**

---

## Layer 4 — Data Safety & Model Loading

**Goal:** Secure model deserialization, ensure DB/filesystem consistency.

### Task 4.1: Secure torch.load and add model checksums

**Issues:** C6 (`torch.load` with `weights_only=False`), I6 (model download no checksum).

**Files:**
- Modify: `src/mbforge/parsers/molecule/molscribe_inference/interface.py`
- Modify: `tests/unit/parsers/test_molscribe_decoder_replay.py`
- Modify: `src/mbforge/core/resource_manager.py`
- Modify: `src/mbforge/models/common.py` or resource info schema

**Interfaces:**
- Consumes: `torch.load`, `ResourceInfo`.
- Produces: `weights_only=True` loading; SHA-256/size verification on download.

**Steps:**
- [ ] **Step 1: Read torch.load call sites and `ResourceInfo`.**
- [ ] **Step 2: Switch to `weights_only=True`; if incompatible, add SHA-256 verification and comment why `weights_only=False` is required.**
- [ ] **Step 3: Add expected hash/size fields to `ResourceInfo`; verify after download.**
- [ ] **Step 4: Update tests.**
- [ ] **Step 5: Run `uv run pytest tests/unit/parsers tests/unit/core/test_resource_manager.py -v`.**
- [ ] **Step 6: Commit.**

### Task 4.2: Ensure DB/filesystem operation consistency

**Issues:** C13 (orphan files/DB inconsistency in library and persist_stage).

**Files:**
- Modify: `src/mbforge/core/library.py`
- Modify: `src/mbforge/pipeline/stages/persist_stage.py`

**Interfaces:**
- Consumes: SQLite transactions, `ArtifactResolver`.
- Produces: Atomic or compensatable persistence operations.

**Steps:**
- [ ] **Step 1: Audit file write/delete vs DB commit ordering.**
- [ ] **Step 2: Reorder so DB record is committed before file is exposed, or add rollback/compensation on failure.**
- [ ] **Step 3: Add tests for failure mid-persist.**
- [ ] **Step 4: Run `uv run pytest tests/unit/core tests/unit/pipeline -v`.**
- [ ] **Step 5: Commit.**

### Task 4.3: Replace popo string-code execution

**Issues:** C12 (`popo.py` executes f-string Python code).

**Files:**
- Modify: `src/mbforge/backends/popo.py`

**Steps:**
- [ ] **Step 1: Read current `popo.py` driver generation.**
- [ ] **Step 2: Replace f-string script with a static driver script that reads config from environment variables or JSON stdin.**
- [ ] **Step 3: Validate/sanitize all injected paths.**
- [ ] **Step 4: Add/update test.**
- [ ] **Step 5: Run `uv run pytest tests/unit/backends/test_popo.py -v` (create if missing).**
- [ ] **Step 6: Commit.**

---

## Layer 5 — Important Fixes & Cleanup

**Goal:** Address remaining Important issues and tool-chain drift.

### Task 5.1: Pipeline correctness and error handling

**Issues:** I1 (`project_root` cleanup), I5 (knowledge_base.search swallows exceptions), I7 (extract_activities leaks API key), I8 (loose substring matching), I9 (stage null derefs), I10 (element whitelist), I11 (MoleCode insertion anchor), I28 (coref_alt swallows exceptions), I29 (stale params/comments).

**Files:**
- Modify: `src/mbforge/pipeline/runner.py`
- Modify: `src/mbforge/core/knowledge_base.py`
- Modify: `src/mbforge/pipeline/extract_activities.py`
- Modify: `src/mbforge/pipeline/normalize.py`
- Modify: `src/mbforge/pipeline/organizer.py`
- Modify: `src/mbforge/parsers/molecule/coref_alt.py`
- Update: `tests/unit/pipeline/`, `AGENTS.md`

**Steps:**
- [ ] **Step 1: Remove `project_root` param and fallback from `run_pipeline`; update callers and tests.**
- [ ] **Step 2: Replace broad `except Exception` in `knowledge_base.search` with specific exceptions or structured fallback.**
- [ ] **Step 3: Do not send real API key to local/self-hosted endpoints in `extract_activities`.**
- [ ] **Step 4: Tighten activity value matching (exact normalized comparison).**
- [ ] **Step 5: Add null checks in stage executors before dereferencing context fields.**
- [ ] **Step 6: Make element whitelist configurable or document the restriction.**
- [ ] **Step 7: Improve MoleCode insertion anchor to use page/line boundaries.**
- [ ] **Step 8: Fix exception swallowing and stale params in `coref_alt`.**
- [ ] **Step 9: Run `uv run pytest tests/unit/pipeline -v`.**
- [ ] **Step 10: Commit.**

### Task 5.2: Core layer improvements

**Issues:** I3 (lifespan prewarm), I4 (DB cache/boundedness, dual connections), I23 (resource_manager None guard, migration duplication, SQL f-string, LIKE escaping, semantic_cache swallowing, file_scanner silent skip, settings redaction, kb router raw root).

**Files:**
- Modify: `src/mbforge/app.py`
- Modify: `src/mbforge/core/database.py`
- Modify: `src/mbforge/core/library.py`
- Modify: `src/mbforge/core/resource_manager.py`
- Modify: `src/mbforge/core/migration.py`
- Modify: `src/mbforge/core/semantic_cache.py`
- Modify: `src/mbforge/core/file_scanner.py`
- Modify: `src/mbforge/routers/settings.py`
- Modify: `src/mbforge/routers/knowledge_base.py`

**Steps:**
- [ ] **Step 1: Await prewarm futures before yielding lifespan or add readiness probe.**
- [ ] **Step 2: Bound DB/store caches with `lru_cache` or TTL; return a single connection per file; fix double-checked locking.**
- [ ] **Step 3: Add None guards in resource_manager.**
- [ ] **Step 4: Deduplicate migration KB schema; use parameterized/whitelisted table names.**
- [ ] **Step 5: Escape `LIKE` wildcards; log semantic_cache exception types; log file_scanner permission warnings.**
- [ ] **Step 6: Fix API key redaction to use word boundaries; pass resolved root to `LibraryLayout`.**
- [ ] **Step 7: Run `uv run pytest tests/unit/core -v`.**
- [ ] **Step 8: Commit.**

### Task 5.3: OpenKB, parsers, and ML backends improvements

**Issues:** I2 (raw dict in routers), I11/I13/I14/I15/I16/I17/I18/I26/I27 already partially covered; I25 (missing tests); M1-M8 (style, dead code, magic numbers, stale comments).

**Files:**
- Modify: `src/mbforge/routers/molecule.py`, `src/mbforge/routers/library.py`, `src/mbforge/routers/agent.py`
- Modify: `src/mbforge/openkb/adapter.py`, `src/mbforge/openkb/query.py`, `src/mbforge/openkb/indexer.py`
- Modify: `src/mbforge/backends/moldet.py`, `src/mbforge/routers/health.py`/`health_router.py`, `src/mbforge/routers/models_router.py`
- Modify: `pyproject.toml`
- Update: `AGENTS.md`, tests

**Steps:**
- [ ] **Step 1: Define Pydantic response models for molecule/library/agent endpoints; replace raw dict returns.**
- [ ] **Step 2: Add size limits to OpenKB wiki file reading; validate copy sources.**
- [ ] **Step 3: Remove dead/duplicate modules (health vs health_router, default_model_dir duplication, placeholder frontend HTTP modules).**
- [ ] **Step 4: Extract magic numbers to config/constants where feasible.**
- [ ] **Step 5: Update stale comments/docstrings; fix ruff target-version to py312; remove stale ignore for `src/mbforge/gui`; add pytest-asyncio config.**
- [ ] **Step 6: Merge duplicate `_utils` frontend tests; fix import order in `test_version_consistency.py`.**
- [ ] **Step 7: Run `uv run ruff check src/` and `uv run pytest tests/unit -v`.**
- [ ] **Step 8: Commit.**

### Task 5.4: Frontend component fixes

**Issues:** I22 (object URL leaks, dead state, logMap unbounded, coref pairing by SMILES, dangerouslySetInnerHTML, PDF.js destroy, etc.), M5 (UI/UX details).

**Files:**
- Modify: `frontend/src/components/project/pdf/usePdfViewer.ts`
- Modify: `frontend/src/components/project/pdf/useIngestPipeline.ts`
- Modify: `frontend/src/components/project/ProcessingQueue.tsx`
- Modify: `frontend/src/components/project/pdf/CorefBboxOverlay.tsx`
- Modify: `frontend/src/components/molecule/MoleculeOverlay.tsx`
- Modify: `frontend/src/components/ui/MermaidCode.tsx`
- Modify: `frontend/src/components/chat/chatUtils.tsx`
- Modify: `frontend/src/components/settings/SettingsPage.tsx`
- Modify: `frontend/src/components/PdfCanvas.tsx`
- Modify: `frontend/src/hooks/useTheme.ts`

**Steps:**
- [ ] **Step 1: Revoke object URLs in cleanup effects.**
- [ ] **Step 2: Fix task lookup dependencies and remove dead `embedState`.**
- [ ] **Step 3: Bound `logMap` and switch to按需 fetching.**
- [ ] **Step 4: Pair coref by `label_id`/prediction relationship, not SMILES string equality.**
- [ ] **Step 5: Sanitize `dangerouslySetInnerHTML` content (DOMPurify or equivalent).**
- [ ] **Step 6: Read system `prefers-color-scheme` for default theme.**
- [ ] **Step 7: Destroy PDF.js document on unmount.**
- [ ] **Step 8: Run `cd frontend && npx tsc --noEmit && npm run test`.**
- [ ] **Step 9: Commit.**

---

## Final Verification & Integration

### Task 6.1: Full test and lint sweep

**Steps:**
- [ ] **Step 1: Run `uv run ruff check src/ tests/` and `uv run ruff format src/ tests/ --check`.**
- [ ] **Step 2: Run `uv run pytest tests/unit -v`.**
- [ ] **Step 3: Run `cd frontend && npx tsc --noEmit && npm run lint && npm run test`.**
- [ ] **Step 4: Run integration smoke tests if available.**
- [ ] **Step 5: Commit any final fixes.**

### Task 6.2: Final whole-branch review

**Steps:**
- [ ] **Step 1: Generate review package (`scripts/review-package BASE HEAD`).**
- [ ] **Step 2: Dispatch final code reviewer subagent.**
- [ ] **Step 3: Address any Critical/Important findings.**
- [ ] **Step 4: Run final verification from Task 6.1 again.**
- [ ] **Step 5: Use `superpowers:finishing-a-development-branch` to decide merge/PR/cleanup.**

---

## Progress Tracking

- Progress ledger: `.superpowers/sdd/progress.md`
- Update after each task with: `Task X.Y: complete (commits <base7>..<head7>, review clean)`
- Do not re-dispatch tasks already marked complete in the ledger.

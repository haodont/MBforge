# Documentation Boundaries Design — 2026-07-10

## Purpose

Record the current project understanding and the 2026-07-10 defect scan in the repository's canonical documentation, then add hard development boundaries so future changes do not repeat the same failure modes.

This is a documentation-governance change. It does not fix product code directly.

## Scope

Update three canonical files after this design is approved:

- `TODO/INDEX.md` — add the dated scan results and repair plan.
- `CLAUDE.md` — add a short high-level guardrail that points contributors to TODO and AGENTS.
- `AGENTS.md` — add mandatory development boundaries with concrete forbidden examples from the audit.

Do not edit unrelated docs. Do not rewrite old TODO sections. Do not duplicate full AGENTS rules into CLAUDE.

## Current Project Understanding

MBForge has a strong product direction and a sound high-level architecture:

```text
PDF -> pipeline -> SQLite/OpenKB/PageIndex -> agent chat + document viewer
```

The five-layer split is still the right model:

```text
Frontend
Routers
Core + Agent + Pipeline
Backends
SQLite + OpenKB + filesystem
```

The main weakness is not the product concept. The weakness is that feature growth has outrun boundary discipline. The current risk clusters are:

- artifact filesystem access leaking into routers;
- DocumentViewer artifact rendering bugs;
- untrusted Markdown rendered too freely;
- pipeline fallback behavior that can silently lose or corrupt source data;
- new code bypassing existing HTTP, logging, config, and test conventions.

## TODO/INDEX.md Design

Add a new dated section near the top, after `Legend` and before the old `Snapshot`.

Section title:

```md
## 2026-07-10 — Artifact / DocumentViewer / Pipeline Hardening Audit
```

Content shape:

- short note that this is the current multi-agent review focus;
- design read summary;
- P0 table for security and boundary blockers;
- P1 table for user-visible correctness and data integrity;
- P2 table for convention and maintenance cleanup;
- refuted candidates table;
- recommended execution order;
- verification commands.

The section must be actionable, not a full prose report. Each finding should include:

- ID;
- area;
- finding;
- files;
- required fix;
- verification.

Planned P0 items:

- artifact APIs use untrusted `doc_id`, `rel_path`, and `project_root` in filesystem joins without a shared resolver;
- `ReorganizedPane` enables raw HTML rendering for PDF/OCR/LLM-controlled Markdown.

Planned P1 items:

- `cropImageUrl()` builds an invalid query string and breaks crop images;
- `language-molecode` is not rendered/clickable;
- `_llm_complete()` can write prompts/wrappers into `reorganized.md` on failure;
- MinerU batch OCR empty pages bypass fallback/retry;
- MoleCode insertion ignores bbox-derived placement and appends at page tail.

Planned P2 items:

- unreachable duplicate code in `organizer.py`;
- raw frontend `fetch` wrappers;
- wiki wrappers that convert failures into empty state;
- cross-directory relative imports;
- new `popo` config field without config tests;
- `popo.py` logger does not use `get_logger(__name__)`.

Refuted item:

- `runner.py` `llm_cfg.model` nil crash is not valid because `AppConfig.llm` has a `default_factory` and invalid config falls back through `load_global_config()`.

Do not merge these findings into the older P0/P1/P2 tables during this change. Keeping a dated section preserves provenance and avoids rewriting old audit history.

## CLAUDE.md Design

Add a short `Current Engineering Guardrails` section near the architecture/read-next area.

The section should say:

- current focus is artifact safety, DocumentViewer correctness, and pipeline data integrity;
- before touching document artifacts, wiki outputs, MoleCode rendering, OCR fallback, or pipeline stages, read the new TODO section and `AGENTS.md § Non-Negotiable Development Boundaries`;
- do not add router-level filesystem joins, raw frontend `fetch`, raw HTML Markdown rendering, or silent error fallbacks;
- if code and docs drift, code wins, but the same change must update `CLAUDE.md`, `AGENTS.md`, and `TODO/INDEX.md` when behavior changes.

CLAUDE.md must stay concise. It is a quick reference, not the detailed rulebook.

## AGENTS.md Design

Add a new section after `Code Conventions & Common Patterns` and before `Settings & Configuration`:

```md
## Non-Negotiable Development Boundaries
```

Rules must use `MUST` / `MUST NOT`. If a task conflicts with them, contributors must stop and ask before coding.

### Artifact and filesystem boundaries

Rules:

- Routers MUST NOT hand-build paths such as `storage/{doc_id}/...`, `.mbforge/crops/{doc_id}/...`, or `.mbforge/openkb/wiki/...`.
- Routers MUST call a service/resolver that validates root, doc_id, rel_path, wiki name, and path containment.
- Path containment MUST use `Path.resolve()` plus `relative_to()` or an equivalent real path containment check. It MUST NOT use `str(path).startswith(...)`.
- Route/query parameters such as `doc_id`, `rel_path`, `project_root`, and wiki `name` MUST be treated as untrusted.

Concrete forbidden examples from the 2026-07-10 audit:

- `Path(root) / "storage" / doc_id / "reorganized.md"` inside a router;
- `str(target).startswith(str(crop_root))` as traversal protection;
- `Path(project_root) / ".mbforge" / "openkb" / "wiki"` directly inside a router.

### Router / service boundary

Rules:

- Routers MUST stay thin: parse request, call service/core, map response.
- Storage layout, artifact naming, OpenKB output layout, and cross-document permission checks MUST live below routers.

### Pipeline boundaries

Rules:

- `runner.py` MUST NOT keep absorbing optional backend-specific logic.
- New pipeline steps SHOULD become bounded stage/helper modules with explicit inputs, outputs, progress events, and tests.
- LLM/OCR fallback MUST preserve source data or fail explicitly.
- LLM/OCR fallback MUST NOT write prompts, wrappers, or partial empty results as if they were successful source data.

### Markdown trust boundary

Rules:

- PDF text, OCR text, LLM output, and reorganized Markdown are untrusted.
- Frontend code MUST NOT enable raw HTML rendering for these sources unless a strict sanitizer allowlist is applied and tested.
- MoleCode/Mermaid rendering MUST handle `language-molecode` explicitly when MoleCode blocks are generated.

### Frontend HTTP boundary

Rules:

- Backend calls MUST go through `frontend/src/api/http/*.ts` wrappers and shared `_utils.ts` error handling.
- Raw `fetch` is allowed only for documented exceptions such as streaming or file downloads, and must preserve explicit error context.
- API wrappers MUST NOT silently convert HTTP 500, validation errors, or network failures into empty UI state.

### Config, logger, tests

Rules:

- New config fields MUST include tests in `tests/unit/test_config.py`.
- Python modules MUST use `get_logger(__name__)`.
- Tests MUST cover why boundary behavior matters: traversal rejection, raw HTML rejection, fallback preserving source text, empty OCR page retry, and MoleCode click metadata.

## Non-Goals

- Do not fix the runtime defects in this documentation change.
- Do not introduce ArtifactService or WikiService in this change.
- Do not reorganize the pipeline runner in this change.
- Do not rewrite the whole TODO board or AGENTS manual.
- Do not commit unless the user explicitly asks for a commit.

## Approval Gate

After this design is approved, implementation can update the three documentation files. The next implementation plan should keep changes minimal and verify by reading the final docs plus checking Markdown structure.

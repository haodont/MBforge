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

Research history is persisted in each library's `research_sessions` table.
The Node sidecar restores Pi conversation files at `LibraryLayout`-controlled
paths and exposes scoped research tools; Python binds credentials, authorization,
visible history, and idempotent queue references. Queue state is not copied into
the conversation store. Stopping a reply does not cancel a background analysis.

The sidecar uses Pi 1.2.0 under `@earendil-works`. Research prompts direct the
assistant to search SQL source text (`search_library`) before drilling into
evidence and accepted facts. Its credential-scoped search preserves the bound
library, pagination and source locations. Optional web research explicitly loads
only the official `@tavily/pi-extension@0.1.2`; global/project extensions, skills
and native tools stay disabled. `web_search` and `web_fetch` reuse that plugin's
provider implementation with MBForge's settings key, limits and redaction. Web
URLs are restricted to public HTTPS sources supplied by the user or discovered
this turn. Web evidence never enters document-local Patent drafting.

Patent facts use SQL `patent_analysis_state` as the committed authority and
`patent_facts.json` as a rebuildable projection. HTTP reads use the same snapshot
reader as review and research tools, returning observed projection status. The
UI displays actual evidence-tool returns separately from semantic adoption and
model-reported coverage. Real-provider scientific evaluation is still pending;
see the [acceptance record](../qa/research-workbench-20261013.md).

Paths have one authority: `LibraryLayout` for library and document paths, plus
the artifact store for document records and cached PDF text. The database remains
a single SQLite file at the library root.

`service/capabilities/` is the single registry of agent-callable tasks. The HTTP
adapter under `api/http/capabilities.py` only resolves the active library,
validates the edit-mode token, and serializes the registry response; it never
reimplements handlers or mode checks. The pi CLI extension consumes the same
manifest, while the web research workspace keeps the Node sidecar for its
credential-scoped turns.

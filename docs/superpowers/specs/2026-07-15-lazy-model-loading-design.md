# Lazy Model Loading Design

## Problem
MBForge currently pre-warms local models (MolDetv2-FT and MolScribe) during application startup in both `mbforge.app:lifespan` and `mbforge.server:lifespan`. This slows down startup and allocates GPU/CPU memory before any request actually needs the models.

## Goal
Remove eager model pre-warming so that local models are loaded only when a pipeline stage or API endpoint first requests them.

## Context
Both backends already implement thread-safe lazy initialization:
- `mbforge.backends.molscribe.load()` uses module-level `_MODEL`, `_AVAILABLE`, `_ERROR`, and `_LOAD_LOCK` with double-checked locking.
- `mbforge.backends.moldet_v2_ft.get_moldet_ft()` uses a module-level `_detector_singleton` and `_detector_lock` with double-checked locking.

Callers that rely on these models already invoke the lazy loaders before use:
- `pipeline/extract_molecules.py` calls `molscribe.load()`.
- `routers/molscribe_api.py` calls `molscribe.load()` before prediction.
- `routers/moldet_api.py` and `parsers/molecule/coref_alt.py` call `get_moldet_ft()` before detection.

The only eager invocation path is `server._prewarm()`, which is called from both lifespans.

## Design
Adopt **Approach A: remove startup pre-warming entirely**.

### Changes
1. Remove `_prewarm()` from `src/mbforge/server.py`.
2. Remove the `_prewarm` import and `prewarm_future` from `src/mbforge/app.py` lifespan; only await `env_future`.
3. Remove the `_prewarm` call from `src/mbforge/server.py` lifespan.

### Behavior after change
- Application startup no longer loads MolDet or MolScribe.
- The first request that needs a model will trigger the existing lazy loader; the request will pay the one-time load latency.
- Subsequent requests reuse the cached singleton.
- `/health` will report `"partial"` until a model is first loaded, then `"online"`.

### Error handling
- Model load failures remain non-fatal and are logged by the existing backend loaders.
- First-request callers receive the existing `model not available` / empty-result fallback behavior if the model file is missing or the environment is unsupported.

## Testing
- Add or update unit tests for `app.py` and `server.py` lifespans to assert that `_prewarm` is not called and that startup completes quickly.
- Verify existing backend lazy-loading tests still pass.
- Run the application and confirm no `"Prewarming ..."` log lines appear at startup; confirm the first molecule-extraction request triggers model load.

## Risks and mitigation
| Risk | Mitigation |
|------|------------|
| First pipeline request becomes slow and appears to hang | Already mitigated by existing lazy loaders; load time is a one-time cost and logged. |
| Health endpoint shows `"partial"` at startup | Expected and accurate; reflects that no model has been loaded yet. |
| Concurrent first requests race to load | Mitigated by existing locks in both backends. |

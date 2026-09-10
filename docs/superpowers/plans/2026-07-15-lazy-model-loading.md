# Lazy Model Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove eager model pre-warming from application startup so MolDetv2-FT and MolScribe are loaded only on first use.

**Architecture:** The backends already have thread-safe lazy loaders (`molscribe.load()` and `moldet_v2_ft.get_moldet_ft()`). This plan removes the only eager invocation path (`server._prewarm()`) and its calls from both FastAPI lifespans. Callers continue to trigger lazy loading as before.

**Tech Stack:** Python 3.12, FastAPI, uv, pytest.

## Global Constraints
- Python 3.12, `uv`, Ruff 88-column format.
- Use `get_logger(__name__)`, never `print()` or bare `except`.
- API boundaries use Pydantic models.
- Add focused regression tests named `test_<behavior>_<scenario>`.

---

### Task 1: Remove `_prewarm` from `mbforge.server` and its lifespan

**Files:**
- Modify: `src/mbforge/server.py:43-80`

**Interfaces:**
- Consumes: nothing (removes dead code).
- Produces: `_prewarm` no longer exists; `lifespan` no longer triggers model load.

- [ ] **Step 1: Delete the `_prewarm` function**

Remove lines 46-70 from `src/mbforge/server.py`:

```python
# DELETE THIS ENTIRE BLOCK
def _prewarm() -> None:
    """Prewarm local model backends in the background.

    Runs inside lifespan via loop.run_in_executor so startup is not blocked.
    Failures are logged as warnings and do not prevent the app from starting.
    """
    try:
        logger.info("Prewarming MolDet...")
        from .backends.moldet_v2_ft import get_moldet_ft

        get_moldet_ft()
        logger.info("MolDetv2-FT prewarm complete")
    except Exception as exc:
        logger.warning("MolDetv2-FT prewarm failed (non-fatal): %s", exc)

    try:
        logger.info("Prewarming MolScribe...")
        from .backends.molscribe import load as load_molscribe

        load_molscribe()
        logger.info("MolScribe prewarm complete")
    except Exception as exc:
        logger.warning("MolScribe prewarm failed (non-fatal): %s", exc)

    logger.info("Model prewarm complete")
```

- [ ] **Step 2: Remove `_prewarm` call from the sidecar lifespan**

In `src/mbforge/server.py`, change the lifespan from:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from .utils.helpers import check_environment, shutdown_backends

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, check_environment)
    loop.run_in_executor(None, _prewarm)
    try:
        yield
    finally:
        shutdown_backends()
```

to:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from .utils.helpers import check_environment, shutdown_backends

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, check_environment)
    try:
        yield
    finally:
        shutdown_backends()
```

- [ ] **Step 3: Verify sidecar server starts without prewarm logs**

Run:

```bash
uv run uvicorn mbforge.server:app --host 127.0.0.1 --port 18793 --log-level info
```

Expected: no `"Prewarming MolDet..."` or `"Prewarming MolScribe..."` logs; startup returns quickly. Stop the server after checking.

---

### Task 2: Remove `_prewarm` from the main application lifespan

**Files:**
- Modify: `src/mbforge/app.py:35-64`

**Interfaces:**
- Consumes: nothing.
- Produces: main app lifespan no longer awaits model pre-warming.

- [ ] **Step 1: Update imports and lifespan body**

In `src/mbforge/app.py`, replace:

```python
from .server import _prewarm
from .utils.helpers import check_environment, shutdown_backends

# Await prewarm before yielding so the app is actually ready to serve
# requests that touch local models. Failures inside the helpers are
# already logged as non-fatal warnings.
loop = asyncio.get_running_loop()
env_future = loop.run_in_executor(None, check_environment)
prewarm_future = loop.run_in_executor(None, _prewarm)
await asyncio.gather(env_future, prewarm_future)
```

with:

```python
from .utils.helpers import check_environment, shutdown_backends

loop = asyncio.get_running_loop()
await loop.run_in_executor(None, check_environment)
```

- [ ] **Step 2: Verify main app starts without prewarm logs**

Run:

```bash
uv run uvicorn mbforge.app:app --host 127.0.0.1 --port 18792 --log-level info
```

Expected: no `"Prewarming MolDet..."` or `"Prewarming MolScribe..."` logs; startup returns quickly. Stop the server after checking.

---

### Task 3: Add regression tests for lazy startup

**Files:**
- Create: `tests/unit/test_lifespan.py`

**Interfaces:**
- Consumes: `mbforge.app.lifespan`, `mbforge.server.lifespan`.
- Produces: tests asserting that prewarm functions are not invoked during lifespan.

- [ ] **Step 1: Write the test**

Create `tests/unit/test_lifespan.py`:

```python
from __future__ import annotations

from contextlib import AsyncExitStack
from unittest.mock import patch

import pytest
from fastapi import FastAPI


@pytest.mark.anyio
async def test_app_lifespan_does_not_load_models() -> None:
    from mbforge.app import lifespan

    app = FastAPI()
    with (
        patch("mbforge.backends.molscribe.load") as mock_molscribe_load,
        patch("mbforge.backends.moldet_v2_ft.get_moldet_ft") as mock_moldet_ft,
    ):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(app))
        mock_molscribe_load.assert_not_called()
        mock_moldet_ft.assert_not_called()


@pytest.mark.anyio
async def test_server_lifespan_does_not_load_models() -> None:
    from mbforge.server import lifespan

    app = FastAPI()
    with (
        patch("mbforge.backends.molscribe.load") as mock_molscribe_load,
        patch("mbforge.backends.moldet_v2_ft.get_moldet_ft") as mock_moldet_ft,
    ):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(app))
        mock_molscribe_load.assert_not_called()
        mock_moldet_ft.assert_not_called()
```

- [ ] **Step 2: Run the tests after implementation**

Run:

```bash
uv run pytest tests/unit/test_lifespan.py -v
```

Expected: both tests pass.

---

### Task 4: Run full verification

**Files:** none (verification only).

- [ ] **Step 1: Python lint and format**

```bash
uv run ruff check src tests
uv run ruff format src tests --check
```

Expected: no errors.

- [ ] **Step 2: Run affected unit tests**

```bash
uv run pytest tests/unit/test_lifespan.py tests/unit/backends/ -q
```

Expected: all pass.

- [ ] **Step 3: Run full unit test suite**

```bash
uv run pytest tests/unit/ -q
```

Expected: all pass (excluding any pre-existing failures unrelated to this change).

---

## Self-Review

**Spec coverage:**
- Remove eager pre-warming: Tasks 1 and 2.
- Preserve lazy loaders: no code changes needed; existing callers remain unchanged.
- Health endpoint behavior: documented in spec; no code change required.
- Testing: Task 3 adds lifespan regression tests; Task 4 verifies.

**Placeholder scan:** no TBD/TODO/fill-in-details found.

**Type consistency:** all mocked functions exist in the current codebase; signatures are unchanged.

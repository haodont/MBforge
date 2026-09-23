"""Ordered shutdown orchestration.

Ensures that when the application exits:
1. Prewarm tasks are cancelled (if any)
2. Queue workers are stopped and their rows released
3. Managed task pools (pipeline / sync / ocr) are drained with a timeout
4. Backend models are unloaded
5. Process registry is unregistered
6. Loop exception handler is restored

This replaces the ad-hoc shutdown in ``app.py`` lifespan and guarantees that
no orphaned processing rows or zombie threads survive process exit.
"""

from __future__ import annotations

import asyncio
import contextlib


def _unload_backends() -> None:
    """Unload all backend model singletons (best-effort).

    Function-level imports: backends must not be loaded just to shut the
    process down, and infra must not statically depend on backends.
    """
    from mbforge.adapters.inference import moldet_v2_ft, molparser

    for mod in (molparser, moldet_v2_ft):
        with contextlib.suppress(Exception):
            mod.unload()


async def orchestrate_shutdown(*, timeout: float = 30.0) -> None:
    """Execute the ordered shutdown sequence.

    Call this from the app lifespan ``finally`` block instead of calling
    individual cleanup functions directly.

    Parameters
    ----------
    timeout : float
        Maximum seconds to wait for the pipeline executor to drain. After
        this deadline we proceed anyway — remaining threads become daemon-like
        and will be killed when the process exits.
    """
    from mbforge.adapters.runtime.ingest import worker

    # Step 1: cancel prewarm task(s) — handled by caller via callback
    # (the prewarm task has its own done-callback that logs failures)

    # Step 2: stop queue workers (this cancels their asyncio tasks;
    #         the worker's finally block releases held rows)
    worker.stop_queue_workers()

    # Step 3: drain every managed pool with timeout
    from mbforge.adapters.runtime.process.tasks import tasks

    pending = await asyncio.wait_for(
        asyncio.to_thread(tasks.shutdown, timeout), timeout=timeout + 5
    )
    if pending > 0:
        from mbforge.foundation.logger import get_logger

        logger = get_logger("mbforge.shutdown")
        logger.warning(
            "%d worker thread(s) did not finish within %.1fs; they will be "
            "killed when the process exits",
            pending,
            timeout,
        )

    # Step 4: unload backend models
    _unload_backends()

    # Step 5: unregister from process registry
    from mbforge.adapters.runtime.process.identity import ProcessRegistry
    from mbforge.foundation.config import load_global_config

    cfg = load_global_config()
    if cfg.library_root:
        try:
            reg = ProcessRegistry.get(cfg.library_root)
            reg.unregister()
        except Exception:
            pass  # Best-effort; don't fail shutdown

    # Step 6: restore loop exception handler — done by caller in app.py

"""Background docking worker.

A per-library asyncio task that claims ``pending`` docking jobs (gated on the
engine/GPU being available) and runs each on the ``DOCKING`` thread pool so the
event loop never blocks. An engine that is not ready leaves jobs ``pending``;
the loop keeps polling so they resume automatically once it is.
"""

from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path

from mbforge.foundation.layout import canonicalize_library_root
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.server.docking.worker")

_POLL_S = 2.0
_workers: dict[str, asyncio.Task] = {}


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def has_worker(library_root: str | Path) -> bool:
    root = str(canonicalize_library_root(library_root))
    task = _workers.get(root)
    return task is not None and not task.done()


def ensure_docking_worker(library_root: str | Path) -> bool:
    """Start the docking worker for a library root if not already running."""
    root = str(canonicalize_library_root(library_root))
    if has_worker(root):
        return True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop (e.g. a sync caller): the next async caller starts it.
        return False
    task = loop.create_task(_loop(root))
    _workers[root] = task
    task.add_done_callback(lambda finished, r=root: _drop(r, finished))
    logger.info("Docking worker started for %s", root)
    return True


def _drop(root: str, task: asyncio.Task) -> None:
    if _workers.get(root) is task:
        _workers.pop(root, None)


def stop_docking_workers() -> None:
    for task in list(_workers.values()):
        if not task.done():
            task.cancel()
    _workers.clear()


def _claim(library_root: str) -> dict | None:
    from mbforge.service.ports import get_repositories

    return get_repositories(library_root).docking.claim_next_pending(_worker_id())


def _mark_failed(library_root: str, job_id: str, error: str) -> None:
    from mbforge.service.ports import get_repositories

    get_repositories(library_root).docking.set_job_status(
        job_id, "failed", error=error[:500], finished=True
    )


def _finalize(library_root: str, job: dict) -> None:
    """Run one job; record success (done) or failure on the row."""
    from mbforge.server.process.tasks import TaskPool, tasks
    from mbforge.service.use_cases.docking import jobs as jobs_uc

    job_id = job["job_id"]
    try:
        tasks.submit(TaskPool.DOCKING, jobs_uc.run_job, library_root, job).result()
    except Exception as exc:  # noqa: BLE001 — failure is recorded, not raised
        logger.error("Docking job %s failed: %s", job_id, exc)
        _mark_failed(library_root, job_id, str(exc))


async def _loop(library_root: str) -> None:
    from mbforge.service.use_cases.docking.engine_gate import evaluate_engine_gate

    try:
        from mbforge.service.ports import get_repositories

        # Recover jobs left ``running`` by a previous process.
        await asyncio.to_thread(
            get_repositories(library_root).docking.reset_running_jobs
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("docking startup recovery failed: %s", exc)

    while True:
        try:
            gate = await asyncio.to_thread(evaluate_engine_gate)
            if gate.ready:
                job = await asyncio.to_thread(_claim, library_root)
                if job is not None:
                    await asyncio.to_thread(_finalize, library_root, job)
        except asyncio.CancelledError:
            logger.info("Docking worker stopped for %s", library_root)
            raise
        except Exception as exc:  # noqa: BLE001 — keep the worker alive
            logger.error("Docking worker loop error: %s", exc, exc_info=True)
        await asyncio.sleep(_POLL_S)


__all__ = ["ensure_docking_worker", "has_worker", "stop_docking_workers"]

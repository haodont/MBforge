"""Unit tests for the unified background task gateway (``infra.process.tasks``).

Covers the two error boundaries the manager exists to protect — a shutdown
drain that actually waits for in-flight work and refuses new work afterwards —
plus the async submission contract.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from mbforge.adapters.runtime.process.tasks import TaskManager, TaskPool


def test_shutdown_waits_for_running_task() -> None:
    """shutdown() blocks until an in-flight task finishes, then reports 0."""
    manager = TaskManager()
    finished = threading.Event()

    def slow() -> None:
        time.sleep(0.2)
        finished.set()

    manager.submit(TaskPool.SYNC, slow)
    remaining = manager.shutdown(timeout=5.0)

    assert remaining == 0
    assert finished.is_set()


def test_shutdown_reports_remaining_on_timeout() -> None:
    """A task outliving the timeout is counted, not silently dropped."""
    manager = TaskManager()
    release = threading.Event()

    manager.submit(TaskPool.SYNC, release.wait, 5)
    remaining = manager.shutdown(timeout=0.2)
    release.set()

    assert remaining > 0


def test_submit_after_shutdown_raises() -> None:
    """No late caller can spin up a fresh pool past shutdown."""
    manager = TaskManager()
    manager.shutdown(timeout=0.1)

    with pytest.raises(RuntimeError):
        manager.submit(TaskPool.SYNC, lambda: None)


def test_run_returns_result() -> None:
    """The async path awaits the pool and returns the task's value."""
    manager = TaskManager()

    async def scenario() -> int:
        try:
            return await manager.run(TaskPool.SYNC, lambda: 21 * 2)
        finally:
            manager.shutdown(timeout=1.0)

    assert asyncio.run(scenario()) == 42

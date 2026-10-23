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

from mbforge.server.process.tasks import TaskManager, TaskPool


def test_shutdown_drains_in_flight_work_and_refuses_new_work() -> None:
    """shutdown() waits for in-flight work, counts what outlives the timeout,
    and no late caller can spin up a fresh pool afterwards."""
    manager = TaskManager()
    finished = threading.Event()

    def slow() -> None:
        time.sleep(0.2)
        finished.set()

    manager.submit(TaskPool.SYNC, slow)
    assert manager.shutdown(timeout=5.0) == 0
    assert finished.is_set()

    timeout_manager = TaskManager()
    release = threading.Event()
    timeout_manager.submit(TaskPool.SYNC, release.wait, 5)
    remaining = timeout_manager.shutdown(timeout=0.2)
    release.set()
    assert remaining > 0

    closed_manager = TaskManager()
    closed_manager.shutdown(timeout=0.1)
    with pytest.raises(RuntimeError):
        closed_manager.submit(TaskPool.SYNC, lambda: None)


def test_run_returns_result() -> None:
    """The async path awaits the pool and returns the task's value."""
    manager = TaskManager()

    async def scenario() -> int:
        try:
            return await manager.run(TaskPool.SYNC, lambda: 21 * 2)
        finally:
            manager.shutdown(timeout=1.0)

    assert asyncio.run(scenario()) == 42

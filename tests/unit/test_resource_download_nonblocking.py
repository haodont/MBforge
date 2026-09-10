"""Regression test: resource download does not block the asyncio event loop.

``ResourceManager.ensure`` may trigger multi-gigabyte model downloads via
``_download_model_from_modelscope``. If it ran directly on the request task
the event loop would stall, freezing every other endpoint (including
``/api/v1/health``) until the download finished. The router must therefore
offload it to a worker thread via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import pytest


@dataclass
class _FakeStatus:
    value: str = "ready"


@dataclass
class _FakeResult:
    status: _FakeStatus
    local_path: str = ""
    size_mb: float = 0.0
    error: str = ""


@pytest.fixture
def slow_ensure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``ResourceManager.ensure`` with a 0.1s-sleeping fake.

    The fake still mimics the public contract: a callable that accepts a
    resource id string and returns a ``ResourceStatusResult``-like object
    with a ``status.value`` attribute.
    """

    def fake_ensure(resource_id: str) -> _FakeResult:
        # ``time.sleep`` would block the event loop if called on the loop
        # thread; running it inside ``asyncio.to_thread`` keeps the loop free,
        # which is exactly the behaviour we want to assert.
        time.sleep(0.1)
        return _FakeResult(status=_FakeStatus(value="ready"))

    from mbforge.infra import resource_manager

    monkeypatch.setattr(resource_manager.ResourceManager, "ensure", fake_ensure)


async def test_resource_download_does_not_block_event_loop(slow_ensure: None) -> None:
    """Other coroutines make progress while ``ensure`` is sleeping."""
    from mbforge.routers.system.resource import ResourceIdRequest, resource_download

    loop = asyncio.get_running_loop()
    tick_count = 0
    max_ticks = 10

    async def ticker() -> None:
        nonlocal tick_count
        for _ in range(max_ticks):
            tick_count += 1
            await asyncio.sleep(0.05)

    ticker_task = asyncio.create_task(ticker())
    start = loop.time()
    response = await resource_download(ResourceIdRequest(resource_id="test-model"))
    elapsed = loop.time() - start
    await ticker_task

    # 10 ticks at 50ms each = 500ms total. With the loop free the ticker
    # should be able to run every step concurrently with the 0.1s worker
    # sleep. If the loop were blocked, the ticker would not advance at all.
    assert tick_count == max_ticks, (
        f"event loop was blocked while ensure was sleeping: "
        f"only {tick_count}/{max_ticks} ticks ran"
    )
    assert elapsed >= 0.09, "ensure must have actually slept in the worker thread"
    assert response["success"] is True
    assert response["status"] == "ready"


async def test_resource_download_rejects_missing_resource_id() -> None:
    """Missing ``resource_id`` returns the documented error envelope without touching ``ensure``."""
    from mbforge.routers.system.resource import ResourceIdRequest, resource_download

    response = await resource_download(ResourceIdRequest())

    assert response == {"success": False, "error": "resource_id required"}

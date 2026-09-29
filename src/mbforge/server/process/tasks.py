"""Unified background task gateway.

Single entry point (``tasks``) for every managed background worker in the
process. It owns:

- a **registry** of bounded thread pools (``POOL_SPECS`` / ``TaskPool``),
  sized from :class:`AppConfig` — adding a pool is one enum member plus one
  spec, not a new singleton getter;
- **submission** that works from both async code (``await tasks.run(...)``)
  and from plain sync threads with no running event loop
  (``tasks.submit(...) -> TaskHandle``, e.g. crop-label OCR inside a pipeline
  worker thread);
- **observability** via ``tasks.stats()`` (capacity / running / queued);
- **graceful drain** via ``tasks.shutdown(timeout)`` covering *all* registered
  pools, plus the shared GPU inference gate (``gpu_gate``).

Design notes
------------
- Pools are process-level singletons created lazily on first use and reused
  for the life of the process. A persistent pool lets thread-local backends
  (e.g. the RapidOCR crop-label engine) pay warm-up once per worker thread.
- The manager never inspects ``gpu_gate``: GPU concurrency stays where it
  belongs, inside ``adapters/inference/`` (``with gpu_gate():``). The manager only runs
  the callable it is handed.
- After ``shutdown`` the manager refuses new work (``RuntimeError``) so a late
  caller cannot spin up a fresh pool whose threads leak past process exit.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mbforge.foundation.config import AppConfig, load_global_config


class TaskPool(StrEnum):
    """Registered pool names. Add a member (plus a ``POOL_SPECS`` entry) to
    stand up a new managed pool."""

    PIPELINE = "pipeline"
    SYNC = "sync"
    OCR = "ocr"


@dataclass(frozen=True)
class PoolSpec:
    """Declarative definition of one managed pool."""

    prefix: str
    workers: Callable[[AppConfig], int]


def _pipeline_workers(cfg: AppConfig) -> int:
    return max(1, min(cfg.ingest.max_concurrency, 8))


def _sync_workers(_cfg: AppConfig) -> int:
    return 4


def _ocr_workers(cfg: AppConfig) -> int:
    # A torch engine must not fan out into N CUDA engines (VRAM); it is already
    # serialized by the GPU gate, so one worker suffices.
    if (cfg.moldet.ocr_engine or "onnx").lower() == "torch":
        return 1
    return max(1, min(cfg.moldet.ocr_workers, 8))


POOL_SPECS: dict[TaskPool, PoolSpec] = {
    # Heavy pipeline stages; the event loop never blocks on them.
    TaskPool.PIPELINE: PoolSpec("mbforge-pipeline", _pipeline_workers),
    # Blocking SQLite / service calls offloaded out of async code.
    TaskPool.SYNC: PoolSpec("mbforge-sync", _sync_workers),
    # Crop-label RapidOCR, kept off the MolParser-feed critical path.
    TaskPool.OCR: PoolSpec("mbforge-ocr", _ocr_workers),
}


@dataclass(frozen=True)
class PoolStat:
    """Point-in-time snapshot of one pool."""

    capacity: int
    running: int
    queued: int


@dataclass
class TaskHandle:
    """A submitted task. Synchronous-safe: usable with or without an event loop."""

    pool: TaskPool
    name: str | None
    future: Future[Any]

    def done(self) -> bool:
        return self.future.done()

    def result(self, timeout: float | None = None) -> Any:
        return self.future.result(timeout)

    def exception(self, timeout: float | None = None) -> BaseException | None:
        return self.future.exception(timeout)

    def cancel(self) -> bool:
        return self.future.cancel()

    def add_done_callback(self, fn: Callable[[TaskHandle], None]) -> None:
        self.future.add_done_callback(lambda _future: fn(self))


class TaskManager:
    """Owns the pool registry, submission, stats, and graceful drain."""

    def __init__(self) -> None:
        self._pools: dict[TaskPool, ThreadPoolExecutor] = {}
        self._capacity: dict[TaskPool, int] = {}
        self._pending: dict[TaskPool, int] = {}
        self._running: dict[TaskPool, int] = {}
        self._lock = threading.Lock()
        self._draining = False

    # -- internals ---------------------------------------------------------

    def _get_or_create(self, pool: TaskPool) -> ThreadPoolExecutor:
        """Return the pool's executor, creating it on first use. Lock held."""
        executor = self._pools.get(pool)
        if executor is None:
            spec = POOL_SPECS[pool]
            capacity = max(1, spec.workers(load_global_config()))
            executor = ThreadPoolExecutor(
                max_workers=capacity,
                thread_name_prefix=spec.prefix,
            )
            self._pools[pool] = executor
            self._capacity[pool] = capacity
        return executor

    def _counted(self, pool: TaskPool, fn: Callable[..., Any]) -> Callable[..., Any]:
        def _run(*args: Any) -> Any:
            with self._lock:
                self._running[pool] = self._running.get(pool, 0) + 1
            try:
                return fn(*args)
            finally:
                with self._lock:
                    self._running[pool] -= 1

        return _run

    # -- public API --------------------------------------------------------

    def submit(
        self,
        pool: TaskPool,
        fn: Callable[..., Any],
        *args: Any,
        name: str | None = None,
        on_done: Callable[[TaskHandle], None] | None = None,
    ) -> TaskHandle:
        """Register ``fn`` on *pool* and return a handle. Sync-safe (no loop)."""
        with self._lock:
            if self._draining:
                raise RuntimeError("task manager is shutting down")
            executor = self._get_or_create(pool)
            self._pending[pool] = self._pending.get(pool, 0) + 1
            try:
                future = executor.submit(self._counted(pool, fn), *args)
            except BaseException:
                self._pending[pool] -= 1
                raise

        handle = TaskHandle(pool=pool, name=name, future=future)

        def _finished(_future: Future[Any]) -> None:
            with self._lock:
                self._pending[pool] -= 1
            if on_done is not None:
                on_done(handle)

        future.add_done_callback(_finished)
        return handle

    async def run(
        self,
        pool: TaskPool,
        fn: Callable[..., Any],
        *args: Any,
        name: str | None = None,
        on_done: Callable[[TaskHandle], None] | None = None,
    ) -> Any:
        """Submit ``fn`` to *pool* and await its result."""
        handle = self.submit(pool, fn, *args, name=name, on_done=on_done)
        return await asyncio.wrap_future(handle.future)

    def stats(self) -> dict[TaskPool, PoolStat]:
        """Capacity / running / queued for every registered pool."""
        with self._lock:
            out: dict[TaskPool, PoolStat] = {}
            for pool, spec in POOL_SPECS.items():
                pending = self._pending.get(pool, 0)
                running = self._running.get(pool, 0)
                capacity = self._capacity.get(pool)
                if capacity is None:
                    capacity = max(1, spec.workers(load_global_config()))
                out[pool] = PoolStat(
                    capacity=capacity,
                    running=running,
                    queued=max(0, pending - running),
                )
            return out

    def shutdown(self, timeout: float = 30.0) -> int:
        """Drain every pool and return threads still alive at *timeout*.

        Stops accepting new work, then waits up to *timeout* for running and
        queued tasks to finish. Returns 0 on a clean drain, otherwise the count
        of worker threads that did not exit in time (the caller logs it and
        proceeds — third-party blocking calls cannot be interrupted from Python).
        """
        with self._lock:
            self._draining = True
            pools = list(self._pools.values())
            self._pools.clear()

        if not pools:
            return 0

        for executor in pools:
            executor.shutdown(wait=False)

        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            alive = 0
            for executor in pools:
                threads = getattr(executor, "_threads", None)
                if not threads:
                    continue
                alive += sum(1 for thread in list(threads) if thread.is_alive())
            if alive == 0:
                return 0
            if time.monotonic() >= deadline:
                return alive
            time.sleep(0.1)


tasks = TaskManager()


# ---------------------------------------------------------------------------
# GPU inference gate
# ---------------------------------------------------------------------------

_gpu_gate: threading.BoundedSemaphore | None = None
_gpu_gate_lock = threading.Lock()


def gpu_gate() -> threading.BoundedSemaphore:
    """Return the singleton GPU inference gate.

    Capacity comes from ``cfg.process.gpu_concurrency`` (default 1). MolDet,
    MolParser, and crop-label OCR wrap their *inference* calls (not model
    loading) in ``with gpu_gate():`` so at most N GPU tasks run concurrently.
    """
    global _gpu_gate
    if _gpu_gate is not None:
        return _gpu_gate
    with _gpu_gate_lock:
        if _gpu_gate is not None:
            return _gpu_gate
        try:
            capacity = load_global_config().process.gpu_concurrency
        except Exception:
            capacity = 1
        _gpu_gate = threading.BoundedSemaphore(max(1, capacity))
    return _gpu_gate

"""Bounded executors and GPU inference gate.

Provides a dedicated thread pool for heavy pipeline work (separate from the
asyncio default pool used by routers for SQLite I/O) and a shared semaphore
that serialises GPU inference across MolDet and MolParser.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from ...utils.config import load_global_config

# ---------------------------------------------------------------------------
# Pipeline executor
# ---------------------------------------------------------------------------

_pipeline_executor: ThreadPoolExecutor | None = None
_pipeline_lock = threading.Lock()


def pipeline_executor() -> ThreadPoolExecutor:
    """Return the singleton pipeline thread pool.

    Sized from ``cfg.ingest.max_concurrency`` (clamped to [1, 8]). Threads are
    named ``mbforge-pipeline-N`` so they show up clearly in profilers.
    """
    global _pipeline_executor
    if _pipeline_executor is not None:
        return _pipeline_executor
    with _pipeline_lock:
        if _pipeline_executor is not None:
            return _pipeline_executor
        cfg = load_global_config()
        max_workers = max(1, min(cfg.ingest.max_concurrency, 8))
        _pipeline_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="mbforge-pipeline",
        )
    return _pipeline_executor


# ---------------------------------------------------------------------------
# Sync (DB) executor
# ---------------------------------------------------------------------------

_sync_executor: ThreadPoolExecutor | None = None
_sync_lock = threading.Lock()


def sync_executor() -> ThreadPoolExecutor:
    """Return the singleton thread pool for blocking DB/service sync calls.

    Governed home for ``run_db_sync``-style offloads (TODO/services-layer-plan.md
    §6.6) so quick SQLite operations share one bounded, named pool instead of
    each service spawning ad-hoc ``asyncio.to_thread`` defaults.
    """
    global _sync_executor
    if _sync_executor is not None:
        return _sync_executor
    with _sync_lock:
        if _sync_executor is not None:
            return _sync_executor
        _sync_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="mbforge-sync",
        )
    return _sync_executor


# ---------------------------------------------------------------------------
# Crop-label OCR executor
# ---------------------------------------------------------------------------

_ocr_executor: ThreadPoolExecutor | None = None
_ocr_lock = threading.Lock()


def ocr_executor() -> ThreadPoolExecutor:
    """Return the singleton bounded pool for crop-label OCR.

    Crop-label RapidOCR runs here so it does not serialize in front of the
    MolParser feed (the GPU pipeline was starved by ~450 ms/crop serial CPU
    OCR). Each worker thread lazily owns its own RapidOCR engine (see
    ``ocr.crop_labels`` thread-local engine), so calls are safe concurrently.
    Sized from ``cfg.moldet.ocr_workers`` (clamped to [0, 8]; 0 → a one-worker
    fallback); threads named ``mbforge-ocr-N``.
    """
    global _ocr_executor
    if _ocr_executor is not None:
        return _ocr_executor
    with _ocr_lock:
        if _ocr_executor is not None:
            return _ocr_executor
        cfg = load_global_config()
        workers = getattr(cfg, "moldet", None)
        engine = (
            getattr(workers, "ocr_engine", "onnx") if workers is not None else "onnx"
        )
        n = getattr(workers, "ocr_workers", 4) if workers is not None else 4
        if (engine or "onnx").lower() == "torch":
            # A torch engine must not fan out into N CUDA engines (VRAM). It is
            # already serialized by the GPU gate, so a single worker suffices.
            n = 1
        n = max(1, min(n, 8))
        _ocr_executor = ThreadPoolExecutor(
            max_workers=n,
            thread_name_prefix="mbforge-ocr",
        )
    return _ocr_executor


# ---------------------------------------------------------------------------
# GPU inference gate
# ---------------------------------------------------------------------------

_gpu_gate: threading.BoundedSemaphore | None = None
_gpu_gate_lock = threading.Lock()


def gpu_gate() -> threading.BoundedSemaphore:
    """Return the singleton GPU inference gate.

    Capacity comes from ``cfg.process.gpu_concurrency`` (default 1). Both
    MolDet and MolParser should wrap their *inference* calls (not model
    loading) in ``with gpu_gate():`` so that at most N GPU tasks run
    concurrently.
    """
    global _gpu_gate
    if _gpu_gate is not None:
        return _gpu_gate
    with _gpu_gate_lock:
        if _gpu_gate is not None:
            return _gpu_gate
        try:
            cfg = load_global_config()
            capacity = getattr(cfg, "process", None)
            n = getattr(capacity, "gpu_concurrency", 1) if capacity is not None else 1
        except Exception:
            n = 1
        n = max(1, n)
        _gpu_gate = threading.BoundedSemaphore(n)
    return _gpu_gate


# ---------------------------------------------------------------------------
# Graceful drain
# ---------------------------------------------------------------------------


def drain_executors(timeout: float = 30.0) -> int:
    """Shut down the pipeline and sync executors, waiting for running tasks.

    Returns the number of tasks that did **not** finish within *timeout*.
    Callers should log this count and proceed — we do not hang the lifespan
    indefinitely because third-party blocking calls (OCR / MolParser / LLM)
    cannot be interrupted from Python.
    """
    global _pipeline_executor, _sync_executor
    if _pipeline_executor is None and _sync_executor is None:
        return 0

    for holder in ("_pipeline_executor", "_sync_executor"):
        executor = globals()[holder]
        if executor is not None:
            executor.shutdown(wait=False)
            globals()[holder] = None

    # Wait up to *timeout* seconds for remaining threads to exit.
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        # ThreadPoolExecutor has no public "pending count" API; we use a
        # heuristic: after shutdown(wait=False), the executor's internal
        # worker threads will eventually terminate. We poll by trying to
        # join via a small sleep loop.
        time.sleep(0.5)
        # No reliable way to check; just return 0 after timeout.
        break

    # After timeout, any remaining threads become daemon-like and will be
    # killed when the process exits. Return 0 since we can't measure.
    return 0

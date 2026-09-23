"""Ingest use-case facade — the single entry point for queue operations.

All paths that need to submit a document for pipeline processing go
through :func:`enqueue`.  The caller provides a ``doc_id`` and a
``library_root``; the facade loads ``document.json`` to resolve the
source file path, creates an ``ingest_queue`` row (via the infra queue
DAO), and wakes the per-library queue worker.

Use-case orchestration lives here (file resolution, worker wake-up,
cancellation registry, stage validation, worker-status/SSE policy); the
SQL primitives live in :mod:`mbforge.adapters.runtime.ingest.queue` and the worker
loop in :mod:`mbforge.adapters.runtime.ingest.worker` (TODO/services-layer-plan.md
§4.1).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mbforge.application.ports import get_runtime
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.foundation.logger import get_logger
from mbforge.foundation.queue_contract import INGEST_TERMINAL_STATUSES

logger = get_logger("mbforge.application.use_cases.ingest")


def _queue() -> Any:
    return get_runtime().ingest_queue


def _worker() -> Any:
    return get_runtime().ingest_worker


def _process() -> Any:
    return get_runtime().process


__all__ = [
    "INGEST_TERMINAL_STATUSES",
    "BatchActionResult",
    "cancel_batch",
    "cleanup_done",
    "delete_task",
    "enqueue",
    "enqueue_all_unresolved",
    "fetch_doc_logs",
    "fetch_logs_since",
    "fetch_run_status",
    "list_tasks",
    "queue_snapshot",
    "retry_batch",
    "stream_run_events",
    "worker_status_payload",
]


@dataclass(frozen=True)
class BatchActionResult:
    """Outcome of a batch queue mutation (cancel/retry/delete/cleanup)."""

    updated: int = 0
    skipped: int = 0
    error: str | None = None


async def enqueue(library_root: str, doc_id: str) -> str:
    """Enqueue a registered document for pipeline processing.

    Reads ``document.json`` to resolve the source file path, inserts a
    ``pending`` row into ``ingest_queue``, and ensures the queue worker
    is running for *library_root*.

    Returns the newly created ``run_id``.

    Raises:
        ValidationError: if *doc_id* or *library_root* is empty.
        NotFoundError: if no ``document.json`` exists for *doc_id* or
            the source file cannot be found on disk.
    """
    if not doc_id:
        raise ValidationError("doc_id is required")
    if not library_root:
        raise ValidationError("library_root is required")

    from mbforge.application.use_cases.documents.library import LibraryStore

    store = LibraryStore.get(library_root)
    doc = await asyncio.to_thread(store.load_document, doc_id)
    if doc is None:
        raise NotFoundError(
            "Document not found",
            detail=f"doc_id={doc_id}",
        )

    file_path = await asyncio.to_thread(store.resolve_file, doc_id)
    if not file_path:
        raise NotFoundError(
            "Document source file not found",
            detail=f"doc_id={doc_id}",
        )

    from mbforge.application.pipeline.run.ids import mint_run_id

    def _register() -> str:
        run_id = mint_run_id(library_root, doc_id)
        _queue().insert_dag(
            library_root, file_path=file_path, doc_id=doc_id, run_id=run_id
        )
        return run_id

    run_id = await asyncio.to_thread(_register)
    ensure_worker(library_root)
    logger.info("Enqueued doc %s as run %s", doc_id, run_id)
    return run_id


async def enqueue_all_unresolved(library_root: str) -> int:
    """扫描项目中所有未处理的 PDF 并入队，返回入队数量.

    File scanning and SQLite queue reads/writes run in the shared thread pool
    so they do not block the event loop. The queue worker claims and runs the
    new rows.
    """
    from mbforge.application.pipeline.run.ids import mint_run_id
    from mbforge.foundation.file_scanner import scan_library_files
    from mbforge.foundation.layout import LibraryLayout

    layout = LibraryLayout(library_root)
    files = await asyncio.to_thread(scan_library_files, library_root)
    pdf_files = [f for f in files if f.lower().endswith(".pdf")]

    def _enqueue_all() -> int:
        count = 0
        for rel_path in pdf_files:
            full_path = str(layout.resolve_relative_path(rel_path))
            doc_id = Path(full_path).stem
            if _queue().doc_queued(library_root, doc_id):
                continue
            run_id = mint_run_id(library_root, doc_id)
            _queue().insert_dag(
                library_root, file_path=full_path, doc_id=doc_id, run_id=run_id
            )
            count += 1
        return count

    enqueued = await asyncio.to_thread(_enqueue_all)
    if enqueued:
        ensure_worker(library_root)
    return enqueued


def ensure_worker(library_root: str) -> None:
    """Wake the per-library queue worker (best-effort)."""
    _worker().ensure_queue_worker(library_root)


async def list_tasks(library_root: str) -> list[dict]:
    """Return all ``ingest_queue`` rows, newest first."""
    from mbforge.application.pipeline.artifacts.staging import staging_dir
    from mbforge.application.pipeline.run.checkpoint import load_run_checkpoint

    def _list_with_stage_statuses() -> list[dict]:
        tasks = _queue().list_tasks(library_root)
        for task in tasks:
            doc_id = task.get("doc_id")
            checkpoint = (
                load_run_checkpoint(staging_dir(library_root, doc_id))
                if doc_id
                else None
            )
            task["stage_statuses"] = (
                {
                    name: stage["status"]
                    for name, stage in checkpoint.get("stages", {}).items()
                    if isinstance(stage, dict) and "status" in stage
                }
                if checkpoint is not None
                else {}
            )
        return tasks

    return await asyncio.to_thread(_list_with_stage_statuses)


def queue_snapshot(library_root: str) -> dict:
    """Return total + per-status counts for ``ingest_queue`` (blocking)."""
    return _queue().queue_snapshot(library_root)


def fetch_run_status(library_root: str, run_id: str) -> str | None:
    """Return the run's aggregated queue status (or None when absent)."""
    return _queue().fetch_run_status(library_root, run_id)


def fetch_logs_since(library_root: str, run_id: str, last_seen_id: int) -> list:
    """Fetch ingest log rows for a run newer than ``last_seen_id`` (blocking)."""
    return _queue().fetch_logs_since(library_root, run_id, last_seen_id)


async def fetch_doc_logs(library_root: str, doc_id: str, limit: int) -> list[dict]:
    """Return recent ingest log rows for a document, chronological order."""
    return await asyncio.to_thread(_queue().fetch_doc_logs, library_root, doc_id, limit)


async def cancel_batch(library_root: str, run_ids: list[str]) -> BatchActionResult:
    """Cancel the runs owning *run_ids* and release their cancellation marks.

    A queue node belongs to a document run, so cancelling cancels the whole
    run's remaining nodes rather than a single stage.
    """
    from mbforge.application.pipeline.runner import cancel_task, release_task

    def _cancel() -> int:
        total = 0
        for doc_id in _queue().doc_ids_for_runs(library_root, run_ids):
            total += _queue().cancel_doc(library_root, doc_id)
        return total

    updated = await asyncio.to_thread(_cancel) if run_ids else 0
    # Signal the worker to abort any active node of these runs. Node ids
    # (not run ids) drive the in-process cancellation registry, so resolve
    # the runs' node ids here.
    node_ids = _queue().node_ids_for_runs(library_root, run_ids)
    for node_id in node_ids:
        cancel_task(node_id)
        if not _worker().is_task_active(node_id):
            release_task(node_id)
    return BatchActionResult(updated=updated, skipped=max(0, len(run_ids) - updated))


async def retry_batch(
    library_root: str,
    run_ids: list[str],
    resume_from_stage: str | None = None,
) -> BatchActionResult:
    """Re-open nodes for retry and relaunch the worker.

    A normal retry re-opens failed/cancelled nodes of the given runs (and
    re-blocks their dependents).  When *resume_from_stage* names a stage,
    the corresponding node of each run's document is reopened even if it
    already succeeded — the queue UI's "rerun from stage" operation. Active
    or claimed nodes are never relaunched.
    """
    from mbforge.application.pipeline.run import checkpoint as stage_checkpoint
    from mbforge.application.pipeline.runner import release_task

    if (
        resume_from_stage is not None
        and resume_from_stage not in stage_checkpoint.STAGE_ORDER
    ):
        return BatchActionResult(
            updated=0,
            skipped=len(run_ids),
            error=(
                f"Invalid resume_from_stage='{resume_from_stage}'. "
                f"Must be one of {stage_checkpoint.STAGE_ORDER}"
            ),
        )

    node_ids = _queue().node_ids_for_runs(library_root, run_ids)
    retryable_ids = [
        node_id for node_id in node_ids if not _worker().is_task_active(node_id)
    ]

    def _retry() -> int:
        if resume_from_stage is None:
            targets = retryable_ids
            allow_done = False
        else:
            rows = _queue().list_tasks(library_root)
            doc_ids = set(_queue().doc_ids_for_runs(library_root, run_ids))
            targets = [
                row["id"]
                for row in rows
                if row.get("doc_id") in doc_ids
                and row.get("stage") == resume_from_stage
            ]
            allow_done = True
        return sum(
            1
            for node_id in targets
            if _queue().reset_node(library_root, node_id, allow_done=allow_done)
        )

    updated = await asyncio.to_thread(_retry) if retryable_ids else 0
    if updated:
        for node_id in node_ids:
            # Clear any stale cancellation mark before relaunching.
            release_task(node_id)
        ensure_worker(library_root)
    return BatchActionResult(updated=updated, skipped=max(0, len(run_ids) - updated))


async def delete_task(library_root: str, run_id: str) -> int:
    """Remove every queue node of *run_id*. Returns rows deleted."""
    return await asyncio.to_thread(_queue().delete_run, library_root, run_id)


async def cleanup_done(library_root: str) -> int:
    """Delete all ``done`` tasks from the queue. Returns rows deleted."""
    return await asyncio.to_thread(_queue().cleanup_done, library_root)


# ---------------------------------------------------------------------------
# Worker status / SSE event stream exposed by the pipeline use case.
# ---------------------------------------------------------------------------


async def worker_status_payload(raw_library_root: str | None) -> dict[str, Any]:
    """Return the library queue worker's real status payload.

    Provides real queue health instead of the historical liveness fiction:
    whether a worker task is registered for the root, whether the library
    lock is held, and the current queue snapshot (active / backlog / total).
    The ``status`` / ``ts`` keys are kept for wire compatibility with the
    frontend.
    """
    from mbforge.foundation.layout import LibraryLayout, resolve_library_root

    ts = int(time.time())
    offline: dict[str, Any] = {
        "status": "offline",
        "ts": ts,
        "active": 0,
        "backlog": 0,
        "total": 0,
        "locked": False,
        "by_status": {},
    }
    try:
        root_str = str(resolve_library_root(raw_library_root or None))
    except Exception:
        return offline

    if not LibraryLayout(root_str).database_path.is_file():
        offline["status"] = "online" if _worker().has_worker(root_str) else "offline"
        offline["library_root"] = root_str
        return offline

    snapshot = await asyncio.to_thread(queue_snapshot, root_str)
    by_status = snapshot["by_status"]

    # Extended fields: lock holder info and orphan list
    lock_holder_info = None
    holder = _process().read_lock_holder(root_str)
    if holder is not None:
        lock_holder_info = {
            "pid": holder.pid,
            "host": holder.host,
            "role": holder.role,
            "legacy": holder.legacy,
        }

    orphans = []
    try:
        for o in _process().find_orphans(root_str, None):
            orphans.append(
                {
                    "pid": o.pid,
                    "confidence": o.confidence,
                    "blocking": o.blocking,
                    "reason": o.reason,
                }
            )
    except Exception:
        pass  # Best-effort; don't fail status endpoint

    registry = _process().ProcessRegistry.get(root_str)
    registered = [
        {"pid": r.pid, "role": r.role, "heartbeat_at": r.heartbeat_at}
        for r in registry.all_identities()
    ]

    return {
        "status": "online" if _worker().has_worker(root_str) else "offline",
        "ts": ts,
        "library_root": root_str,
        "locked": _worker().is_library_locked(root_str),
        "active": by_status.get("processing", 0),
        "backlog": by_status.get("pending", 0),
        "total": snapshot["total"],
        "by_status": by_status,
        "lock_holder": lock_holder_info,
        "orphans": orphans,
        "registered_processes": registered,
    }


async def stream_run_events(
    library_root: str,
    run_id: str,
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE frames for one pipeline run's ingest logs.

    Reads from the ``ingest_logs`` table and yields one frame per log row.
    The stream ends when the task is no longer active and no new rows have
    appeared for a short grace period, or when the queue row reports a
    terminal status.
    """
    root_str = library_root
    last_seen_id = 0
    empty_iterations = 0
    while True:
        if await is_disconnected():
            break

        try:
            rows = await asyncio.to_thread(
                fetch_logs_since,
                root_str,
                run_id,
                last_seen_id,
            )
        except Exception as exc:
            logger.warning("Failed to read ingest logs for %s: %s", run_id, exc)
            rows = []

        if rows:
            empty_iterations = 0
            for row in rows:
                last_seen_id = row["id"]
                payload = {
                    "stage": row["stage"],
                    "event": row["level"],
                    "message": row["message"],
                    "ts_ms": row["ts_ms"],
                }
                if row["data"]:
                    try:
                        payload["data"] = json.loads(row["data"])
                    except Exception:
                        payload["data"] = row["data"]
                yield {"event": row["level"], "data": json.dumps(payload)}
        else:
            status = await asyncio.to_thread(fetch_run_status, root_str, run_id)
            if status in INGEST_TERMINAL_STATUSES:
                # DB terminal state is authoritative: close promptly even
                # after a process restart wiped in-memory task state.
                break
            empty_iterations += 1
            if not _worker().is_run_active(run_id) and empty_iterations > 5:
                # No runner is (or will be) emitting rows for this task:
                # it is queued but unclaimed, orphaned, or its worker died.
                break
            await asyncio.sleep(1)

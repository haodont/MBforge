"""Ingest use-case facade — the single entry point for queue operations.

All paths that need to submit a document for pipeline processing go
through :func:`enqueue`.  The caller provides a ``doc_id`` and a
``library_root``; the facade loads ``document.json`` to resolve the
source file path, creates an ``ingest_queue`` row (via the infra queue
DAO), and wakes the per-library queue worker.

Use-case orchestration lives here (file resolution, worker wake-up,
cancellation registry, stage validation, worker-status/SSE policy); the
SQL primitives live in :mod:`mbforge.infra.ingest.queue` and the worker
loop in :mod:`mbforge.infra.ingest.worker` (TODO/services-layer-plan.md
§4.1).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ...storage.sqlite.database import INGEST_TERMINAL_STATUSES
from ...utils.errors import NotFoundError, ValidationError
from ...utils.logger import get_logger

logger = get_logger("mbforge.services.ingest")

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
    "fetch_task_status",
    "list_tasks",
    "queue_snapshot",
    "retry_batch",
    "stream_task_events",
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

    Returns the newly created ``task_id``.

    Raises:
        ValidationError: if *doc_id* or *library_root* is empty.
        NotFoundError: if no ``document.json`` exists for *doc_id* or
            the source file cannot be found on disk.
    """
    if not doc_id:
        raise ValidationError("doc_id is required")
    if not library_root:
        raise ValidationError("library_root is required")

    from ..documents.library import LibraryStore

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

    from ...infra.ingest import queue as queue_dao

    task_id = await asyncio.to_thread(
        queue_dao.insert_pending, library_root, file_path=file_path, doc_id=doc_id
    )
    ensure_worker(library_root)
    logger.info("Enqueued doc %s as task %s", doc_id, task_id)
    return task_id


async def enqueue_all_unresolved(library_root: str) -> int:
    """扫描项目中所有未处理的 PDF 并入队，返回入队数量.

    File scanning and SQLite queue reads/writes run in the shared thread pool
    so they do not block the event loop. The queue worker claims and runs the
    new rows.
    """
    from ...infra.ingest import queue as queue_dao
    from ...storage.layout import LibraryLayout
    from ...utils.file_scanner import scan_library_files

    layout = LibraryLayout(library_root)
    files = await asyncio.to_thread(scan_library_files, library_root)
    pdf_files = [f for f in files if f.lower().endswith(".pdf")]

    def _enqueue_all() -> int:
        count = 0
        for rel_path in pdf_files:
            full_path = str(layout.resolve_relative_path(rel_path))
            if queue_dao.insert_pending_if_absent(library_root, full_path):
                count += 1
        return count

    enqueued = await asyncio.to_thread(_enqueue_all)
    if enqueued:
        ensure_worker(library_root)
    return enqueued


def ensure_worker(library_root: str) -> None:
    """Wake the per-library queue worker (best-effort)."""
    from ...infra.ingest import worker

    worker.ensure_queue_worker(library_root)


async def list_tasks(library_root: str) -> list[dict]:
    """Return all ``ingest_queue`` rows, newest first."""
    from ...infra.ingest import queue as queue_dao
    from ...pipeline.run_artifacts import staging_dir
    from ...pipeline.stage_checkpoint import load_run_checkpoint

    def _list_with_stage_statuses() -> list[dict]:
        tasks = queue_dao.list_tasks(library_root)
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
    from ...infra.ingest import queue as queue_dao

    return queue_dao.queue_snapshot(library_root)


def fetch_task_status(library_root: str, task_id: str) -> str | None:
    """Return the task's current queue status (or None when it is absent)."""
    from ...infra.ingest import queue as queue_dao

    return queue_dao.fetch_task_status(library_root, task_id)


def fetch_logs_since(library_root: str, task_id: str, last_seen_id: int) -> list:
    """Fetch ingest log rows newer than ``last_seen_id`` (blocking)."""
    from ...infra.ingest import queue as queue_dao

    return queue_dao.fetch_logs_since(library_root, task_id, last_seen_id)


async def fetch_doc_logs(library_root: str, doc_id: str, limit: int) -> list[dict]:
    """Return recent ingest log rows for a document, chronological order."""
    from ...infra.ingest import queue as queue_dao

    return await asyncio.to_thread(
        queue_dao.fetch_doc_logs, library_root, doc_id, limit
    )


async def cancel_batch(library_root: str, task_ids: list[str]) -> BatchActionResult:
    """Cancel pending/processing tasks and release their cancellation marks."""
    from ...infra.ingest import queue as queue_dao
    from ...infra.ingest import worker
    from ...pipeline.runner import cancel_task, release_task

    updated = await asyncio.to_thread(
        queue_dao.set_status_cancelled, library_root, task_ids
    )
    # Signal the runner to abort running tasks. A task that is not currently
    # executing in this process (still queued, orphaned, or between runs) can
    # never hit the runner's terminal-state cleanup, so its cancellation
    # registry entry is released here; a running task is released by the
    # runner's own finally block instead.
    for task_id in task_ids:
        cancel_task(task_id)
        if not worker.is_task_active(task_id):
            release_task(task_id)
    return BatchActionResult(updated=updated, skipped=len(task_ids) - updated)


async def retry_batch(
    library_root: str,
    task_ids: list[str],
    resume_from_stage: str | None = None,
) -> BatchActionResult:
    """Reset retryable tasks to ``pending`` and relaunch the worker.

    A normal retry targets failed or cancelled tasks.  A caller that explicitly
    chooses *resume_from_stage* may also restart a completed task from that
    checkpoint; this is the per-task "rerun from stage" operation exposed by
    the queue UI.  In either case, active or claimed tasks are never relaunched.
    """
    from ...infra.ingest import queue as queue_dao
    from ...infra.ingest import worker
    from ...pipeline import stage_checkpoint
    from ...pipeline.run_artifacts import staging_dir
    from ...pipeline.runner import release_task

    # Validate resume_from_stage if provided.
    if (
        resume_from_stage is not None
        and resume_from_stage not in stage_checkpoint.STAGE_ORDER
    ):
        return BatchActionResult(
            updated=0,
            skipped=len(task_ids),
            error=(
                f"Invalid resume_from_stage='{resume_from_stage}'. "
                f"Must be one of {stage_checkpoint.STAGE_ORDER}"
            ),
        )

    retryable_ids = [
        task_id for task_id in task_ids if not worker.is_task_active(task_id)
    ]

    def _retry() -> list[dict[str, str]]:
        tasks = {task["id"]: task for task in queue_dao.list_tasks(library_root)}
        if resume_from_stage is None:
            retry_ids = [
                task_id
                for task_id in retryable_ids
                if tasks.get(task_id, {}).get("status") in {"failed", "cancelled"}
                and not tasks.get(task_id, {}).get("claimed_by")
            ]
        else:
            retry_ids = retryable_ids

        if resume_from_stage in {"extract", "detection"}:
            for task_id in retry_ids:
                task = tasks.get(task_id)
                if (
                    task
                    and task.get("status") in {"done", "failed", "cancelled"}
                    and not task.get("claimed_by")
                    and task.get("doc_id")
                ):
                    task_staging = staging_dir(library_root, task["doc_id"])
                    stage_checkpoint.reset_stage_for_retry(
                        task_staging, resume_from_stage
                    )
                    stage_checkpoint.reset_stage_for_retry(task_staging, "join")
        return queue_dao.retry_rows(
            library_root, retry_ids, resume_from_stage=resume_from_stage
        )

    relaunched = await asyncio.to_thread(_retry) if retryable_ids else []
    for row in relaunched:
        # Clear any stale cancellation mark before relaunching.
        release_task(row["id"])
    if relaunched:
        ensure_worker(library_root)
    return BatchActionResult(
        updated=len(relaunched), skipped=len(task_ids) - len(relaunched)
    )


async def delete_task(library_root: str, task_id: str) -> int:
    """Remove a single task row from the queue. Returns rows deleted."""
    from ...infra.ingest import queue as queue_dao

    return await asyncio.to_thread(queue_dao.delete_task, library_root, task_id)


async def cleanup_done(library_root: str) -> int:
    """Delete all ``done`` tasks from the queue. Returns rows deleted."""
    from ...infra.ingest import queue as queue_dao

    return await asyncio.to_thread(queue_dao.cleanup_done, library_root)


# ---------------------------------------------------------------------------
# Worker status / SSE event stream (moved from routers/pipeline/pipeline.py,
# TODO/services-layer-plan.md A7).
# ---------------------------------------------------------------------------


async def worker_status_payload(raw_library_root: str | None) -> dict[str, Any]:
    """Return the library queue worker's real status payload.

    Provides real queue health instead of the historical liveness fiction:
    whether a worker task is registered for the root, whether the library
    lock is held, and the current queue snapshot (active / backlog / total).
    The ``status`` / ``ts`` keys are kept for wire compatibility with the
    frontend.
    """
    from ...infra.ingest import worker
    from ...infra.process import ProcessRegistry, find_orphans, read_lock_holder
    from ...storage.layout import LibraryLayout, resolve_library_root

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
        offline["status"] = "online" if worker.has_worker(root_str) else "offline"
        offline["library_root"] = root_str
        return offline

    snapshot = await asyncio.to_thread(queue_snapshot, root_str)
    by_status = snapshot["by_status"]

    # Extended fields: lock holder info and orphan list
    lock_holder_info = None
    holder = read_lock_holder(root_str)
    if holder is not None:
        lock_holder_info = {
            "pid": holder.pid,
            "host": holder.host,
            "role": holder.role,
            "legacy": holder.legacy,
        }

    orphans = []
    try:
        for o in find_orphans(root_str, None):
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

    registry = ProcessRegistry.get(root_str)
    registered = [
        {"pid": r.pid, "role": r.role, "heartbeat_at": r.heartbeat_at}
        for r in registry.all_identities()
    ]

    return {
        "status": "online" if worker.has_worker(root_str) else "offline",
        "ts": ts,
        "library_root": root_str,
        "locked": worker.is_library_locked(root_str),
        "active": by_status.get("processing", 0),
        "backlog": by_status.get("pending", 0),
        "total": snapshot["total"],
        "by_status": by_status,
        "lock_holder": lock_holder_info,
        "orphans": orphans,
        "registered_processes": registered,
    }


async def stream_task_events(
    library_root: str,
    task_id: str,
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE frames for one pipeline task's ingest logs.

    Reads from the ``ingest_logs`` table and yields one frame per log row.
    The stream ends when the task is no longer active and no new rows have
    appeared for a short grace period, or when the queue row reports a
    terminal status.
    """
    from ...infra.ingest import worker

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
                task_id,
                last_seen_id,
            )
        except Exception as exc:
            logger.warning("Failed to read ingest logs for %s: %s", task_id, exc)
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
            status = await asyncio.to_thread(fetch_task_status, root_str, task_id)
            if status in INGEST_TERMINAL_STATUSES:
                # DB terminal state is authoritative: close promptly even
                # after a process restart wiped in-memory task state.
                break
            empty_iterations += 1
            if not worker.is_task_active(task_id) and empty_iterations > 5:
                # No runner is (or will be) emitting rows for this task:
                # it is queued but unclaimed, orphaned, or its worker died.
                break
            await asyncio.sleep(1)

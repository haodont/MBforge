"""Per-library durable pipeline queue worker.

Each library root gets at most one worker (per process) that owns the
``ingest_queue`` rows for that
root:

- Claims ``pending`` rows atomically with a single UPDATE
  (``RETURNING``), so two workers — even in two processes sharing one
  library — can never run the same task.
- Runs ``run_pipeline`` in the shared thread pool so the event loop is
  never blocked.
- Heartbeats claimed rows while a task is executing so a crash/restart can
  be distinguished from a genuinely long run, and reclaims rows whose
  heartbeat went stale (orphaned by a killed process) back into ``pending``
  on the next drain pass. Rows executing inside this process are never
  reclaimed, even when a heartbeat write is delayed.

A per-root file lock (``{root}/queue.lock``) enforces the
single-owner decision: exactly one process may drain a library's queue.
A second MBForge process still enqueues rows normally (they land in the
shared SQLite database) and the lock-holding worker picks them up. If the
lock is unavailable the worker logs a hint and idles, retrying periodically
in case the current owner exits.

The pipeline runner owns the terminal state transitions (success → ``done``,
failure → ``failed``, cancellation → ``cancelled``) via ``record_ingest_event``;
this module only claims rows and applies a last-resort terminal status for
exceptions raised before the runner could record anything.
"""

# Tests:
#   tests/conftest.py
#   tests/unit/infra/test_queue_worker.py
#   tests/unit/pipeline/test_cancellation.py
#   tests/unit/routers/test_pipeline.py
#   tests/unit/test_routers_smoke.py

from __future__ import annotations

import asyncio
import functools
import os
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger

if TYPE_CHECKING:
    from mbforge.service.use_cases.pipeline.model_gate import ModelGateResult

logger = get_logger("mbforge.queue_worker")

# Poll cadence for claiming/reclaiming/heartbeating.
_CLAIM_POLL_S = 2.0
# A claimed row whose heartbeat is older than this is treated as orphaned and
# reclaimed into ``pending``.
_HEARTBEAT_STALE_S = 60.0
# How long a follower (no library lock) waits before retrying to become the
# leader.
_LOCK_RETRY_S = 10.0
# Model gate probe cadence.  The probe stats model directories, so it costs
# more than a claim poll; the verdict is cached between iterations and only
# refreshed this often.
_GATE_POLL_S = 5.0

# Task ids currently executing inside THIS process, grouped by library root
# (event-loop thread only). Grouping by root lets a multi-library process
# stop or fail one worker without forgetting another worker's active tasks.
_active_task_ids: dict[str, set[str]] = {}
_active_run_ids: set[str] = set()
# per-root worker tasks (event-loop thread only).
_workers: dict[str, asyncio.Task] = {}


def _worker_id() -> str:
    """Return a stable-ish worker identity for ``claimed_by``."""
    return f"{socket.gethostname()}:{os.getpid()}:{short_id()}"


def is_task_active(task_id: str) -> bool:
    """Return True if ``task_id`` is executing inside this process right now."""
    return any(task_id in ids for ids in _active_task_ids.values())


def is_run_active(run_id: str) -> bool:
    """Return True if any node of ``run_id`` is executing here now."""
    return run_id in _active_run_ids


def _active_for(library_root: str) -> set[str]:
    """Return the (mutable) set of active task ids for a library root."""
    return _active_task_ids.setdefault(library_root, set())


def has_worker(library_root: str | Path) -> bool:
    """Return True when a worker task is registered for the root."""
    from mbforge.foundation.layout import canonicalize_library_root

    root = str(canonicalize_library_root(library_root))
    task = _workers.get(root)
    return task is not None and not task.done()


def ensure_queue_worker(library_root: str | Path) -> bool:
    """Start the queue worker for ``library_root`` if it is not running.

    Must be called from an asyncio event loop (routers, app lifespan).
    Returns True when a worker task is (already) registered.
    """
    from mbforge.foundation.layout import canonicalize_library_root

    root = str(canonicalize_library_root(library_root))
    if has_worker(root):
        return True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("ensure_queue_worker for %s requires a running event loop", root)
        return False
    task = loop.create_task(_worker_loop(root))
    _workers[root] = task
    task.add_done_callback(functools.partial(_drop_worker, root=root))
    logger.info("Queue worker ensured for %s", root)
    return True


def _drop_worker(task: asyncio.Task, *, root: str) -> None:
    """Remove a finished worker from the registry (idempotent)."""
    if _workers.get(root) is task:
        _workers.pop(root, None)


def stop_queue_worker(library_root: str | Path) -> None:
    """Cancel the queue worker for one root (best-effort)."""
    from mbforge.foundation.layout import canonicalize_library_root

    root = str(canonicalize_library_root(library_root))
    task = _workers.pop(root, None)
    if task is not None and not task.done():
        task.cancel()


def stop_queue_workers() -> None:
    """Cancel every registered worker (call from app shutdown)."""
    for task in list(_workers.values()):
        if not task.done():
            task.cancel()
    _workers.clear()


async def _worker_loop(library_root: str) -> None:
    worker = _worker_id()
    logger.info("Queue worker started for %s [%s]", library_root, worker)

    # Register as queue-leader when we acquire the lock.  The worker may be
    # launched for a library root that differs from the process-wide default
    # (for example, a request-scoped library or an isolated test library), so
    # its process identity must follow the root owned by this worker.
    from mbforge.server.process import ProcessRegistry, read_lock_holder

    registry = ProcessRegistry.get(library_root)

    last_holder_pid: int | None = None
    first_follower_warn = True

    try:
        while True:
            try:
                with _library_lock(library_root) as held:
                    if not held:
                        # Report lock holder info on first warning or when it changes
                        holder = read_lock_holder(library_root)
                        current_pid = holder.pid if holder else None
                        if first_follower_warn or current_pid != last_holder_pid:
                            holder_info = (
                                f" (held by PID {current_pid})" if current_pid else ""
                            )
                            logger.warning(
                                "Queue worker for %s is a follower: another process owns "
                                "the library lock%s; tasks will be claimed by the leader",
                                library_root,
                                holder_info,
                            )
                            first_follower_warn = False
                            last_holder_pid = current_pid
                        else:
                            logger.debug(
                                "Queue worker for %s is a follower (PID %s still holds lock)",
                                library_root,
                                current_pid,
                            )
                        await asyncio.sleep(_LOCK_RETRY_S)
                        continue

                    # We are the leader — register and heartbeat
                    if registry is not None:
                        registry.register("queue-leader")
                    # Reclaim only after taking the library lock. A follower
                    # must never reset rows owned by the current leader.
                    _reclaim_all_processing_on_startup(library_root, worker)
                    first_follower_warn = True
                    last_holder_pid = None
                    await _drain_loop(library_root, worker)
            except asyncio.CancelledError:
                logger.info("Queue worker stopped for %s", library_root)
                raise
            except Exception as exc:  # noqa: BLE001 — keep the worker alive
                logger.error(
                    "Queue worker for %s faulted: %s", library_root, exc, exc_info=True
                )
                await asyncio.sleep(_CLAIM_POLL_S)
    finally:
        if registry is not None:
            registry.unregister()


def _evaluate_model_gate() -> ModelGateResult:
    """Probe whether the required pipeline models are ready.

    Lazily imports the use case so this module keeps its ``foundation``-only
    import surface.  Module-level name so tests can replace it, mirroring the
    ``ensure_queue_worker`` / ``_run_pipeline_sync`` convention.
    """
    from mbforge.service.use_cases.pipeline.model_gate import evaluate_model_gate

    return evaluate_model_gate()


async def _drain_loop(library_root: str, worker: str) -> None:
    """Claim tasks until cancelled, then drain and release this worker's rows.

    Claiming is gated on the required models being ready: while any is missing
    the loop leaves rows ``pending`` and keeps polling, so tasks queue up
    instead of failing and resume on their own once the downloads land.  The
    gate only guards *claiming* — in-flight tasks and orphan reclaiming are
    untouched.
    """
    active = _active_for(library_root)
    running: set[asyncio.Task] = set()
    gate: ModelGateResult | None = None
    gate_missing: tuple[str, ...] | None = None
    next_gate_check = 0.0
    try:
        while True:
            _reclaim_orphans(library_root, excluded_ids=active)
            slots = _max_concurrency() - len(running)
            if slots > 0:
                now = time.monotonic()
                if gate is None or now >= next_gate_check:
                    gate = await asyncio.to_thread(_evaluate_model_gate)
                    next_gate_check = now + _GATE_POLL_S
                if gate.ready:
                    if gate_missing is not None:
                        logger.info(
                            "Required models ready; resuming the ingest queue for %s",
                            library_root,
                        )
                        gate_missing = None
                    claimed = _claim_rows(library_root, worker, slots)
                    for row in claimed:
                        active.add(row["id"])
                        task = asyncio.create_task(
                            _execute_claimed(library_root, row, worker)
                        )
                        running.add(task)
                        task.add_done_callback(running.discard)
                else:
                    # Log once per distinct missing set, not on every poll.
                    missing = gate.missing_ids()
                    if missing != gate_missing:
                        logger.warning(
                            "Ingest queue for %s paused: %s",
                            library_root,
                            gate.reason(),
                        )
                        gate_missing = missing
            if running:
                _heartbeat_rows(library_root, worker)
                await asyncio.wait(set(running), timeout=_CLAIM_POLL_S)
            else:
                await asyncio.sleep(_CLAIM_POLL_S)
    finally:
        # Ask in-flight pipelines to stop before releasing their claims. This
        # prevents a new worker from running the same task while an executor
        # thread is still writing its current stage.
        if active:
            from mbforge.service.ports import get_pipeline_runtime

            runtime = get_pipeline_runtime()
            for task_id in tuple(active):
                runtime.cancel_task(task_id)
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        _release_current_worker_rows(library_root, worker)
        # Drop this root's tracking without touching any other library's active set.
        active.clear()
        _active_task_ids.pop(library_root, None)


async def _execute_claimed(library_root: str, row: dict[str, Any], worker: str) -> None:
    """Run one claimed queue row in the shared thread pool."""
    task_id = row["id"]
    run_id = row.get("run_id")
    if run_id:
        _active_run_ids.add(run_id)
    try:
        from mbforge.server.process import TaskPool, tasks

        await tasks.run(
            TaskPool.PIPELINE,
            _run_pipeline_sync,
            row["file_path"],
            library_root,
            row["doc_id"] or "",
            task_id,
            row["stage"],
            row["run_id"],
        )
        logger.debug("Queue task %s finished", task_id)
    finally:
        from mbforge.service.ports import get_pipeline_runtime

        # Covers the small race where cancellation is requested after
        # run_pipeline has already reached its own finally block.
        get_pipeline_runtime().release_task(task_id)
        active = _active_for(library_root)
        active.discard(task_id)
        if run_id:
            _active_run_ids.discard(run_id)
        if not active:
            _active_task_ids.pop(library_root, None)


def _run_pipeline_sync(
    file_path: str,
    library_root: str,
    doc_id: str,
    task_id: str,
    stage: str,
    run_id: str | None,
) -> None:
    """Execute one queue node, then advance the document's stage DAG.

    Each row is a single DAG node. On success the node is marked ``done`` and
    its newly-satisfied dependents are promoted from ``blocked`` to
    ``pending``; once every node of the run is ``done`` the run is published
    exactly once. On failure the node is marked ``failed`` and its transitive
    dependents cascade to ``failed`` so the document reaches an explicit
    terminal state.
    """
    from mbforge.server.ingest import queue as queue_dao
    from mbforge.service.ports import TaskCancelledError, get_pipeline_runtime

    try:
        get_pipeline_runtime().run_pipeline(
            file_path,
            library_root,
            doc_id=doc_id,
            stage=stage,
            run_id=run_id,
            task_id=task_id,
        )
    except TaskCancelledError as exc:
        logger.info("Pipeline cancelled for %s: %s", file_path, exc)
        queue_dao.set_node_status(library_root, task_id, "cancelled", str(exc))
        # A cancelled run produced no results, so the document goes back to
        # ``pending`` and stays hidden from the workspace listing until a run
        # reaches an outcome. The queue page still offers a retry.
        _set_document_status(library_root, doc_id, "pending")
        return
    except Exception as exc:  # noqa: BLE001
        logger.error("Stage %s failed for %s: %s", stage, file_path, exc, exc_info=True)
        queue_dao.set_node_status(library_root, task_id, "failed", str(exc))
        if doc_id and run_id:
            queue_dao.fail_cascade(
                library_root,
                doc_id=doc_id,
                run_id=run_id,
                failed_stage=stage,
                error=str(exc),
            )
        # Surface the failure in the workspace rather than hiding it forever.
        _set_document_status(library_root, doc_id, "error")
        return

    queue_dao.set_node_status(library_root, task_id, "done")
    if not (doc_id and run_id):
        return
    queue_dao.advance_dependents(
        library_root, doc_id=doc_id, run_id=run_id, completed_stage=stage
    )
    if queue_dao.all_stages_done(
        library_root, doc_id=doc_id, run_id=run_id
    ) and queue_dao.claim_finalize(library_root, doc_id=doc_id, run_id=run_id):
        try:
            _write_final_report(library_root, doc_id, task_id)
        except Exception:  # noqa: BLE001 — no published output means no "ready"
            _set_document_status(library_root, doc_id, "error")
            raise
        # Every stage of this run succeeded and the run published exactly once.
        # A run that did not include Patent only extracted the document, so it
        # rests at ``extracted``; a run with Patent is fully analyzed (``ready``).
        stages = queue_dao.stages_in_run(library_root, doc_id=doc_id, run_id=run_id)
        final_status = "ready" if "patent" in stages else "extracted"
        _set_document_status(library_root, doc_id, final_status)
        logger.debug("Task %s: all stages complete (%s)", task_id, final_status)


def _set_document_status(library_root: str, doc_id: str, status: str) -> None:
    """Record a document's processing outcome for the workspace listing.

    The workspace shows documents that reached a resting status
    (``extracted``/``ready``/``error``), so each terminal queue transition
    writes the registry row here. Failures are logged rather than raised — the
    queue node's own status remains the authoritative record of the run.
    """
    if not doc_id:
        return
    from mbforge.service.ports import get_repositories

    try:
        get_repositories(library_root).documents.update_status(doc_id, status)
    except Exception as exc:  # noqa: BLE001 — status write must not mask the run
        logger.warning("Failed to mark document %s as %s: %s", doc_id, status, exc)


def _write_final_report(library_root: str, doc_id: str, task_id: str) -> None:
    """Write the merged document_report.json, then promote staged evidence.

    The report must be written *before* promotion because promote_staging
    deletes the staging directory (which holds the checkpoint files).
    """
    from mbforge.service.ports import get_pipeline_runtime

    runtime = get_pipeline_runtime()
    staging = runtime.staging_dir(library_root, doc_id)
    try:
        runtime.write_merged_report(staging, doc_id=doc_id, library_root=library_root)
        runtime.promote_staging(staging, library_root, doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to finalize pipeline output for %s: %s", doc_id, exc)
        raise


def _max_concurrency() -> int:
    """Read the configured pipeline concurrency for this library."""
    try:
        from mbforge.foundation.config import load_global_config

        return max(1, min(int(load_global_config().ingest.max_concurrency), 8))
    except Exception:  # noqa: BLE001
        return 1


def _claim_rows(library_root: str, worker: str, limit: int) -> list[dict[str, Any]]:
    """Atomically claim up to ``limit`` pending rows for ``worker``."""
    from mbforge.db.sqlite.database import DatabaseManager

    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        rows = conn.execute(
            """
            UPDATE ingest_queue
            SET status = 'processing',
                claimed_by = ?,
                heartbeat_ts = datetime('now'),
                updated_at = datetime('now')
            WHERE id IN (
                SELECT id FROM ingest_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
            )
            RETURNING id, file_path, doc_id, stage, run_id
            """,
            (worker, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def _reclaim_all_processing_on_startup(library_root: str, worker: str) -> None:
    """Reclaim rows left by a worker that exited without terminal cleanup.

    This ensures that tasks orphaned by a killed process do not linger in
    ``processing`` indefinitely, and terminal rows do not remain permanently
    claimed after a cancelled process. The current worker will pick pending
    rows up on the next claim cycle, so no manual retry is required.
    """
    from mbforge.db.sqlite.database import DatabaseManager

    sql = """
        UPDATE ingest_queue
        SET status = 'pending',
            claimed_by = NULL,
            heartbeat_ts = NULL,
            updated_at = datetime('now')
        WHERE status = 'processing'
          AND claimed_by != ?
    """
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        cursor = conn.execute(sql, (worker,))
        if cursor.rowcount:
            logger.info(
                "Startup reclamation: reset %d processing rows to pending for %s",
                cursor.rowcount,
                library_root,
            )
        terminal_cursor = conn.execute(
            "UPDATE ingest_queue SET claimed_by = NULL, heartbeat_ts = NULL, "
            "updated_at = datetime('now') "
            "WHERE status IN ('done', 'failed', 'cancelled') "
            "AND claimed_by IS NOT NULL"
        )
        if terminal_cursor.rowcount:
            logger.info(
                "Startup reclamation: cleared %d terminal claims for %s",
                terminal_cursor.rowcount,
                library_root,
            )


def _release_current_worker_rows(library_root: str, worker: str) -> None:
    """Reset all rows claimed by ``worker`` back to ``pending`` on exit.

    Called from the worker's finally block so that a cancelled or crashed
    worker does not leave orphaned ``processing`` rows behind. The next
    worker (or this one on restart) will pick them up automatically.
    """
    from mbforge.db.sqlite.database import DatabaseManager

    sql = """
        UPDATE ingest_queue
        SET status = 'pending',
            claimed_by = NULL,
            heartbeat_ts = NULL,
            updated_at = datetime('now')
        WHERE status = 'processing'
          AND claimed_by = ?
    """
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        cursor = conn.execute(sql, (worker,))
        if cursor.rowcount:
            logger.info(
                "Shutdown release: reset %d processing rows to pending for %s [%s]",
                cursor.rowcount,
                library_root,
                worker,
            )


def _reclaim_orphans(library_root: str, excluded_ids: set[str] | None = None) -> int:
    """Return ``processing`` rows with a stale/missing heartbeat to ``pending``.

    ``excluded_ids`` holds task ids executing inside this process; those rows
    are never reclaimed, even if a heartbeat write was delayed or the worker
    is mid-drain. This is the authoritative guard against double-execution —
    heartbeat freshness is a heuristic for foreign rows only.
    """
    from mbforge.db.sqlite.database import DatabaseManager

    excluded = excluded_ids or set()
    sql = """
        UPDATE ingest_queue
        SET status = 'pending',
            claimed_by = NULL,
            heartbeat_ts = NULL,
            updated_at = datetime('now')
        WHERE status = 'processing'
          AND (
              claimed_by IS NULL
              OR heartbeat_ts IS NULL
              OR datetime(heartbeat_ts) < datetime('now', ? )
          )
    """
    params: list[Any] = [f"-{_HEARTBEAT_STALE_S} seconds"]
    if excluded:
        placeholders = ",".join("?" for _ in excluded)
        sql += f" AND id NOT IN ({placeholders})"
        params.extend(excluded)
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        cursor = conn.execute(sql, params)
        if cursor.rowcount:
            logger.warning(
                "Reclaimed %d orphaned queue rows for %s",
                cursor.rowcount,
                library_root,
            )
        return cursor.rowcount


def _heartbeat_rows(library_root: str, worker: str) -> None:
    """Refresh the heartbeat of every row claimed by ``worker`` in this root."""
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.foundation.config import load_global_config
    from mbforge.server.process import ProcessRegistry

    task_ids = list(_active_for(library_root))
    if not task_ids:
        return
    db = DatabaseManager.get(library_root)
    placeholders = ",".join("?" for _ in task_ids)
    with db.kb_conn() as conn:
        conn.execute(
            f"UPDATE ingest_queue SET heartbeat_ts = datetime('now'), "
            f"updated_at = datetime('now') "
            f"WHERE id IN ({placeholders}) AND claimed_by = ?",
            [*task_ids, worker],
        )

    # Also heartbeat the process registry entry (if we are the leader)
    try:
        cfg = load_global_config()
        if cfg.library_root:
            reg = ProcessRegistry.get(cfg.library_root)
            reg.heartbeat()
    except Exception:
        pass  # Best-effort; don't fail heartbeat


# ---------------------------------------------------------------------------
# Library lock: one process may drain a library's queue at a time.
# ---------------------------------------------------------------------------
# Library lock wrappers — delegate to ``infra.process.filelock``.
# ---------------------------------------------------------------------------


@contextmanager
def _library_lock(library_root: str) -> Iterator[bool]:
    """Yield True when this process acquired the library lock."""
    from mbforge.foundation.layout import LibraryLayout
    from mbforge.server.process.filelock import (
        LockMeta,
        queue_lock_path,
        try_lock_file,
        unlock_file,
    )

    layout = LibraryLayout(library_root)
    layout.ensure_library_root()
    lock_path = queue_lock_path(library_root)
    lock_file = try_lock_file(
        lock_path,
        LockMeta(
            pid=os.getpid(),
            host=socket.gethostname(),
            role="queue-worker",
            started_at=time.time(),
        ),
    )
    try:
        yield lock_file is not None
    finally:
        if lock_file is not None:
            unlock_file(lock_file)


def is_library_locked(library_root: str | Path) -> bool:
    """Return True when another process holds the library lock.

    Read-only probe: unlike ``_library_lock`` it never creates the library
    root or the lock file, so ``GET /worker/status`` has no filesystem
    side effects when no worker has ever started for the library.
    """
    from mbforge.server.process.filelock import (
        queue_lock_path,
        try_lock_existing,
        unlock_file,
    )

    lock_path = queue_lock_path(library_root)
    if not lock_path.is_file():
        return False
    handle = try_lock_existing(lock_path)
    if handle is None:
        return True
    unlock_file(handle)
    return False

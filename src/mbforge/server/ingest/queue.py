"""Ingest queue DAO — SQL primitives over the ``ingest_queue``/``ingest_logs`` tables.

This module owns the queue's data access only. Use-case orchestration
(file resolution, worker wake-up, cancellation registry, stage validation)
lives in :mod:`mbforge.service.use_cases.pipeline.ingest`.
"""

# Tests:
#   tests/unit/infra/test_queue_worker.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.server.ingest")


def insert_dag(
    library_root: str,
    *,
    file_path: str,
    doc_id: str,
    run_id: str,
    stages: Sequence[str] | None = None,
) -> None:
    """Register the stage DAG for one document run.

    One ``ingest_queue`` row per stage (roots ``pending``, everything else
    ``blocked``) plus one ``ingest_stage_deps`` edge per prerequisite, all
    carrying *run_id* so the row's stage is executed against the same
    attempt. Earlier **finished** runs of the same document are superseded:
    their rows and edges are removed so the queue holds exactly one live run
    per document. An in-flight run is never deleted here — callers must cancel
    it first (see ``use_cases.pipeline.ingest.enqueue``), so a re-import cannot
    silently drop a processing node and leave two writers on the same doc.

    When *stages* is given, only those stages are scheduled. Prerequisites
    outside the selected set are dropped, so a lone ``("patent",)`` run makes
    ``patent`` a root node that is admitted immediately (its real data
    dependency — the SQL ``source_evidence`` rows — is checked by the runner's
    hydration, not by the queue DAG).

    Idempotent for the same ``(doc_id, run_id)`` via the unique node index.
    """
    from mbforge.service.ports import get_pipeline_runtime

    deps = get_pipeline_runtime().stage_dependencies()
    if stages is not None:
        selected = list(dict.fromkeys(stages))
        deps = {
            stage: tuple(prereq for prereq in deps.get(stage, ()) if prereq in selected)
            for stage in selected
        }
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        conn.execute(
            "DELETE FROM ingest_queue WHERE doc_id = ? AND run_id != ? "
            "AND status IN ('done', 'failed', 'cancelled')",
            (doc_id, run_id),
        )
        conn.execute(
            "DELETE FROM ingest_stage_deps WHERE doc_id = ? AND run_id != ? "
            "AND run_id NOT IN (SELECT DISTINCT run_id FROM ingest_queue WHERE doc_id = ?)",
            (doc_id, run_id, doc_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO ingest_runs (doc_id, run_id) VALUES (?, ?)",
            (doc_id, run_id),
        )
        for stage, prereqs in deps.items():
            conn.execute(
                "INSERT OR IGNORE INTO ingest_queue "
                "(id, file_path, doc_id, stage, run_id, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    short_id(),
                    file_path,
                    doc_id,
                    stage,
                    run_id,
                    "pending" if not prereqs else "blocked",
                ),
            )
            for prereq in prereqs:
                conn.execute(
                    "INSERT OR IGNORE INTO ingest_stage_deps "
                    "(doc_id, run_id, stage, depends_on) VALUES (?, ?, ?, ?)",
                    (doc_id, run_id, stage, prereq),
                )


def set_node_status(
    library_root: str,
    task_id: str,
    status: str,
    error: str | None = None,
) -> bool:
    """Set one node's status; returns True when a claimed row was updated."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        cursor = conn.execute(
            "UPDATE ingest_queue SET status = ?, error = ?, "
            "claimed_by = NULL, heartbeat_ts = NULL, updated_at = datetime('now') "
            "WHERE id = ? AND claimed_by IS NOT NULL",
            (status, error, task_id),
        )
        return cursor.rowcount == 1


def _dependents(conn: Any, doc_id: str, run_id: str, stage: str) -> list[str]:
    return [
        row["stage"]
        for row in conn.execute(
            "SELECT stage FROM ingest_stage_deps "
            "WHERE doc_id = ? AND run_id = ? AND depends_on = ?",
            (doc_id, run_id, stage),
        ).fetchall()
    ]


def advance_dependents(
    library_root: str,
    *,
    doc_id: str,
    run_id: str,
    completed_stage: str,
) -> list[str]:
    """Promote dependents of *completed_stage* that are now fully satisfied.

    A dependent moves ``blocked`` → ``pending`` only when **every** one of
    its prerequisites is ``done``. The ``status = 'blocked'`` guard makes the
    promotion idempotent, so re-promoting the same node is a no-op.
    """
    db = DatabaseManager.get(library_root)
    promoted: list[str] = []
    with db.connection() as conn:
        for stage in _dependents(conn, doc_id, run_id, completed_stage):
            unmet = conn.execute(
                "SELECT COUNT(*) FROM ingest_stage_deps d "
                "WHERE d.doc_id = ? AND d.run_id = ? AND d.stage = ? "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM ingest_queue q "
                "  WHERE q.doc_id = d.doc_id AND q.run_id = d.run_id "
                "    AND q.stage = d.depends_on AND q.status = 'done'"
                ")",
                (doc_id, run_id, stage),
            ).fetchone()[0]
            if unmet:
                continue
            cursor = conn.execute(
                "UPDATE ingest_queue SET status = 'pending', "
                "updated_at = datetime('now') "
                "WHERE doc_id = ? AND run_id = ? AND stage = ? AND status = 'blocked'",
                (doc_id, run_id, stage),
            )
            if cursor.rowcount:
                promoted.append(stage)
    return promoted


def fail_cascade(
    library_root: str,
    *,
    doc_id: str,
    run_id: str,
    failed_stage: str,
    error: str,
) -> list[str]:
    """Mark every transitive dependent of a failed node ``failed``.

    Keeps the document in an explicit terminal state instead of leaving
    its downstream nodes ``blocked`` forever.
    """
    db = DatabaseManager.get(library_root)
    cascaded: list[str] = []
    with db.connection() as conn:
        frontier = [failed_stage]
        seen: set[str] = set()
        while frontier:
            for stage in _dependents(conn, doc_id, run_id, frontier.pop()):
                if stage in seen:
                    continue
                seen.add(stage)
                cursor = conn.execute(
                    "UPDATE ingest_queue SET status = 'failed', error = ?, "
                    "claimed_by = NULL, heartbeat_ts = NULL, "
                    "updated_at = datetime('now') "
                    "WHERE doc_id = ? AND run_id = ? AND stage = ? "
                    "AND status = 'blocked'",
                    (error, doc_id, run_id, stage),
                )
                if cursor.rowcount:
                    cascaded.append(stage)
                    frontier.append(stage)
    return cascaded


def all_stages_done(library_root: str, *, doc_id: str, run_id: str) -> bool:
    """Return True when every node of the run has status ``done``."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM ingest_queue WHERE doc_id = ? AND run_id = ?",
            (doc_id, run_id),
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM ingest_queue WHERE doc_id = ? AND run_id = ? "
            "AND status = 'done'",
            (doc_id, run_id),
        ).fetchone()[0]
    return total > 0 and total == done


def claim_finalize(library_root: str, *, doc_id: str, run_id: str) -> bool:
    """Atomically claim the right to publish this run; True exactly once."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        cursor = conn.execute(
            "UPDATE ingest_runs SET finalized = 1 "
            "WHERE doc_id = ? AND run_id = ? AND finalized = 0 "
            "AND EXISTS (SELECT 1 FROM ingest_queue WHERE doc_id = ? AND run_id = ?) "
            "AND NOT EXISTS (SELECT 1 FROM ingest_queue WHERE doc_id = ? AND run_id = ? AND status != 'done')",
            (doc_id, run_id, doc_id, run_id, doc_id, run_id),
        )
        return cursor.rowcount == 1


def stages_in_run(library_root: str, *, doc_id: str, run_id: str) -> list[str]:
    """Return the stage names scheduled for a run, in insertion order.

    A run may hold only a subset of the pipeline stages (import schedules
    Extract + Markdown; Patent analysis schedules Patent alone), so the
    finalizer uses this to decide the document's resting status.
    """
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT stage FROM ingest_queue WHERE doc_id = ? AND run_id = ?",
            (doc_id, run_id),
        ).fetchall()
        return [row["stage"] for row in rows]


def run_ids_for_doc(library_root: str, doc_id: str) -> list[str]:
    """Return the distinct run IDs already queued for a document."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT run_id FROM ingest_queue "
            "WHERE doc_id = ? AND run_id IS NOT NULL",
            (doc_id,),
        ).fetchall()
        return [row["run_id"] for row in rows]


def node_ids_for_runs(library_root: str, run_ids: list[str]) -> list[str]:
    """Return the ``ingest_queue`` node ids belonging to *run_ids* (order kept)."""
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT id FROM ingest_queue WHERE run_id IN ({placeholders})",
            run_ids,
        ).fetchall()
        return [row["id"] for row in rows]


def doc_ids_for_runs(library_root: str, run_ids: list[str]) -> list[str]:
    """Return the distinct ``doc_id`` values owning *run_ids* (order kept)."""
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT doc_id FROM ingest_queue WHERE run_id IN ({placeholders}) AND doc_id IS NOT NULL",
            run_ids,
        ).fetchall()
        return [row["doc_id"] for row in rows]


def cancel_doc(library_root: str, doc_id: str) -> int:
    """Cancel every non-terminal node of *doc_id*; returns rows updated."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        cursor = conn.execute(
            "UPDATE ingest_queue SET status = 'cancelled', "
            "updated_at = datetime('now') "
            "WHERE doc_id = ? AND status IN ('pending', 'processing', 'blocked')",
            (doc_id,),
        )
        return cursor.rowcount


def reset_node(library_root: str, task_id: str, *, allow_done: bool = False) -> bool:
    """Re-open one node and re-block its transitive dependents.

    ``allow_done=False`` (default) retries a failed/cancelled node; ``True``
    also re-opens a node that already succeeded, which is how the UI's
    "rerun from stage" reaches back into a completed run. Dependents go back
    to ``blocked`` so they cannot run until the reopened node succeeds again.
    Nodes that already succeeded are left untouched, so a retry reuses their
    artifacts.
    """
    allowed = ("done", "failed", "cancelled") if allow_done else ("failed", "cancelled")
    placeholders = ",".join("?" for _ in allowed)
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT doc_id, run_id, stage FROM ingest_queue WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        doc_id, run_id, stage = row["doc_id"], row["run_id"], row["stage"]
        cursor = conn.execute(
            f"UPDATE ingest_queue SET status = 'pending', error = NULL, "
            f"claimed_by = NULL, heartbeat_ts = NULL, "
            f"retry_count = retry_count + 1, updated_at = datetime('now') "
            f"WHERE id = ? AND status IN ({placeholders})",
            (task_id, *allowed),
        )
        if not cursor.rowcount:
            return False
        conn.execute(
            "UPDATE ingest_runs SET finalized = 0 WHERE doc_id = ? AND run_id = ?",
            (doc_id, run_id),
        )
        frontier = [stage]
        seen: set[str] = set()
        while frontier:
            for dep in _dependents(conn, doc_id, run_id, frontier.pop()):
                if dep in seen:
                    continue
                seen.add(dep)
                conn.execute(
                    "UPDATE ingest_queue SET status = CASE "
                    "WHEN status IN ('done', 'failed', 'cancelled') THEN 'blocked' "
                    "ELSE status END, error = NULL, updated_at = datetime('now') "
                    "WHERE doc_id = ? AND run_id = ? AND stage = ? "
                    "AND status != 'processing'",
                    (doc_id, run_id, dep),
                )
                frontier.append(dep)
        return True


def doc_queued(library_root: str, doc_id: str) -> bool:
    """Return True when *doc_id* already has any queue row (any status)."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM ingest_queue WHERE doc_id = ? LIMIT 1", (doc_id,)
        ).fetchone()
    return row is not None


def active_run_id(library_root: str, doc_id: str) -> str | None:
    """Return the run_id of *doc_id* with a non-terminal node, if any.

    A non-terminal node (``pending``/``processing``/``blocked``) means the
    document has an in-flight run; ``enqueue`` reuses it (or, when forced,
    cancels it) instead of deleting its rows out from under a live writer.
    """
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT run_id FROM ingest_queue "
            "WHERE doc_id = ? AND status IN ('pending', 'processing', 'blocked') "
            "LIMIT 1",
            (doc_id,),
        ).fetchone()
    return row["run_id"] if row is not None else None


def _task_dict(row: Any) -> dict:
    return {
        key: value
        for key, value in dict(row).items()
        if key not in {"progress_pct", "pages_total", "pages_done"}
    }


def list_tasks(library_root: str) -> list[dict]:
    """Return all ``ingest_queue`` rows, newest first (blocking)."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ingest_queue ORDER BY created_at DESC"
        ).fetchall()
    return [_task_dict(row) for row in rows]


def list_run_tasks(library_root: str, run_id: str) -> list[dict]:
    """Return the queue rows belonging to one run, newest first (blocking)."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ingest_queue WHERE run_id = ? ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
    return [_task_dict(row) for row in rows]


def list_runs(
    library_root: str,
    *,
    doc_id: str | None = None,
    active_only: bool = True,
    limit: int = 20,
) -> list[dict]:
    """Return up to *limit* runs grouped from their queue nodes, newest first.

    A run is one ``run_id`` with its stage nodes. ``active_only`` keeps runs
    whose aggregate status is ``pending``/``processing``/``blocked``: a run
    with any failed or cancelled node is terminal and is excluded even when a
    sibling node is still pending.

    Filtering happens on the run-level status, never on individual nodes, so a
    returned run always carries every node of its DAG.
    """
    db = DatabaseManager.get(library_root)
    clauses = ["run_id IS NOT NULL"]
    params: list[Any] = []
    if doc_id:
        clauses.append("doc_id = ?")
        params.append(doc_id)
    having = ""
    if active_only:
        having = (
            " HAVING SUM(CASE WHEN status IN "
            "('pending', 'processing', 'blocked') THEN 1 ELSE 0 END) > 0"
            " AND SUM(CASE WHEN status IN ('failed', 'cancelled') "
            "THEN 1 ELSE 0 END) = 0"
        )
    with db.connection() as conn:
        candidates = conn.execute(
            f"SELECT run_id FROM ingest_queue WHERE {' AND '.join(clauses)} "
            f"GROUP BY run_id{having} ORDER BY MAX(created_at) DESC LIMIT ?",
            [*params, max(1, limit)],
        ).fetchall()
        run_ids = [str(row["run_id"]) for row in candidates]
        if not run_ids:
            return []
        placeholders = ", ".join("?" for _ in run_ids)
        rows = conn.execute(
            f"SELECT * FROM ingest_queue WHERE run_id IN ({placeholders}) "
            "ORDER BY created_at ASC",
            run_ids,
        ).fetchall()

    grouped: dict[str, list[dict]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped.setdefault(str(row["run_id"]), []).append(_task_dict(row))
    result: list[dict] = []
    for run_id in run_ids:
        nodes = grouped.get(run_id) or []
        if not nodes:
            continue
        result.append(
            {
                "run_id": run_id,
                "doc_id": nodes[0].get("doc_id"),
                "status": _worst_status(
                    [str(node.get("status") or "") for node in nodes]
                )
                or "unknown",
                "created_at": min(
                    (str(node.get("created_at") or "") for node in nodes),
                    default="",
                ),
                "updated_at": max(
                    (str(node.get("updated_at") or "") for node in nodes),
                    default="",
                ),
                "nodes": nodes,
            }
        )
    return result


def queue_snapshot(library_root: str) -> dict:
    """Return total + per-status counts for ``ingest_queue`` (blocking)."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM ingest_queue").fetchone()[0]
        by_status = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM ingest_queue GROUP BY status"
            ).fetchall()
        }
    return {"total": total, "by_status": by_status}


#: Run-level status precedence: a terminal failure outranks active work, and
#: an active stage outranks a blocked/done tail.
_RUN_STATUS_PRECEDENCE = {
    "cancelled": 0,
    "failed": 1,
    "processing": 2,
    "pending": 3,
    "blocked": 4,
    "done": 5,
}


def _worst_status(statuses: Sequence[str]) -> str | None:
    """Aggregate node statuses into one run status by worst precedence."""
    if not statuses:
        return None
    worst = min(
        (_RUN_STATUS_PRECEDENCE.get(status, 99) for status in statuses), default=99
    )
    for status, rank in _RUN_STATUS_PRECEDENCE.items():
        if rank == worst:
            return status
    return statuses[0]


def fetch_run_status(library_root: str, run_id: str) -> str | None:
    """Aggregate a run's status across its queue nodes by worst precedence.

    One ``run_id`` spans several stage nodes; aggregate with terminal states
    winning over active ones so the UI shows a stable run-level status:
    cancelled/failed > processing > pending > done.
    """
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT status FROM ingest_queue
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
    return _worst_status([str(row["status"]) for row in rows])


def fetch_logs_since(library_root: str, run_id: str, last_seen_id: int) -> list:
    """Fetch ingest log rows for a run newer than ``last_seen_id`` (blocking)."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        return conn.execute(
            """
            SELECT id, stage, level, message, data, ts_ms
            FROM ingest_logs
            WHERE run_id = ? AND id > ?
            ORDER BY id ASC
            """,
            (run_id, last_seen_id),
        ).fetchall()


def fetch_doc_logs(library_root: str, doc_id: str, limit: int) -> list[dict]:
    """Return recent ingest log rows for a document, chronological order."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT doc_id, stage, level, message, ts_ms, task_id
            FROM ingest_logs
            WHERE doc_id = ?
            ORDER BY ts_ms ASC, id ASC
            LIMIT ?
            """,
            (doc_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_run(library_root: str, run_id: str) -> int:
    """Remove all ``ingest_queue`` rows of *run_id*. Returns rows deleted."""
    db = DatabaseManager.get(library_root)
    with db.connection() as conn:
        cursor = conn.execute("DELETE FROM ingest_queue WHERE run_id = ?", (run_id,))
        return cursor.rowcount

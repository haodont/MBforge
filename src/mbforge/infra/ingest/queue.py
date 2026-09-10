"""Ingest queue DAO — SQL primitives over the ``ingest_queue``/``ingest_logs`` tables.

Moved from ``services/ingest_queue.py`` (TODO/services-layer-plan.md A6):
this module owns the queue's data access only. Use-case orchestration
(file resolution, worker wake-up, cancellation registry, stage validation)
lives in :mod:`mbforge.services.pipeline.ingest`.
"""

from __future__ import annotations

import uuid
from typing import Any

from ...storage.sqlite.database import DatabaseManager
from ...utils.logger import get_logger

logger = get_logger("mbforge.infra.ingest")


def insert_pending(
    library_root: str,
    *,
    file_path: str,
    doc_id: str | None = None,
) -> str:
    """Insert one ``pending`` row; returns the generated task id."""
    task_id = str(uuid.uuid4())
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        conn.execute(
            """
            INSERT INTO ingest_queue
                (id, file_path, doc_id, status, created_at)
            VALUES (?, ?, ?, 'pending', datetime('now'))
            """,
            (task_id, file_path, doc_id),
        )
    return task_id


def insert_pending_if_absent(library_root: str, file_path: str) -> bool:
    """Insert a ``pending`` row for *file_path* unless one already exists."""
    db = DatabaseManager.get(library_root)
    task_id = str(uuid.uuid4())
    with db.kb_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM ingest_queue WHERE file_path = ?", (file_path,)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO ingest_queue (id, file_path, status, created_at) "
            "VALUES (?, ?, 'pending', datetime('now'))",
            (task_id, file_path),
        )
    return True


def list_tasks(library_root: str) -> list[dict]:
    """Return all ``ingest_queue`` rows, newest first (blocking)."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ingest_queue ORDER BY created_at DESC"
        ).fetchall()
        return [
            {
                key: value
                for key, value in dict(row).items()
                if key not in {"progress_pct", "pages_total", "pages_done"}
            }
            for row in rows
        ]


def queue_snapshot(library_root: str) -> dict:
    """Return total + per-status counts for ``ingest_queue`` (blocking)."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM ingest_queue").fetchone()[0]
        by_status = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM ingest_queue GROUP BY status"
            ).fetchall()
        }
    return {"total": total, "by_status": by_status}


def fetch_task_status(library_root: str, task_id: str) -> str | None:
    """Return the task's current queue status (or None when it is absent)."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        row = conn.execute(
            "SELECT status FROM ingest_queue WHERE id = ?", (task_id,)
        ).fetchone()
    return row["status"] if row else None


def fetch_logs_since(library_root: str, task_id: str, last_seen_id: int) -> list:
    """Fetch ingest log rows newer than ``last_seen_id`` (blocking)."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        return conn.execute(
            """
            SELECT id, stage, level, message, data, ts_ms
            FROM ingest_logs
            WHERE task_id = ? AND id > ?
            ORDER BY id ASC
            """,
            (task_id, last_seen_id),
        ).fetchall()


def fetch_doc_logs(library_root: str, doc_id: str, limit: int) -> list[dict]:
    """Return recent ingest log rows for a document, chronological order."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
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


def delete_task(library_root: str, task_id: str) -> int:
    """Remove a single task row from the queue. Returns rows deleted."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        cursor = conn.execute("DELETE FROM ingest_queue WHERE id = ?", (task_id,))
        return cursor.rowcount


def cleanup_done(library_root: str) -> int:
    """Delete all ``done`` tasks from the queue. Returns rows deleted."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        cursor = conn.execute("DELETE FROM ingest_queue WHERE status = 'done'")
        return cursor.rowcount


def set_status_cancelled(library_root: str, task_ids: list[str]) -> int:
    """Cancel pending/processing queue rows; returns rows updated."""
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        placeholders = ",".join("?" for _ in task_ids)
        cursor = conn.execute(
            f"UPDATE ingest_queue SET status = 'cancelled', "
            f"updated_at = datetime('now') "
            f"WHERE id IN ({placeholders}) AND status IN ('pending', 'processing')",
            task_ids,
        )
        return cursor.rowcount


def retry_rows(
    library_root: str,
    task_ids: list[str],
    *,
    resume_from_stage: str | None = None,
) -> list[dict[str, str]]:
    """Reset unclaimed terminal rows to ``pending``.

    When *resume_from_stage* is given, the stage checkpoint column is reset
    so the runner starts from that stage instead of the last checkpoint.
    A still-claimed task is left terminal so an old executor cannot race a
    newly relaunched copy.
    """
    db = DatabaseManager.get(library_root)
    with db.kb_conn() as conn:
        placeholders = ",".join("?" for _ in task_ids)
        stage_update = ""
        params: list[Any] = list(task_ids)
        if resume_from_stage is not None:
            stage_update = "stage = ?, "
            params.insert(0, resume_from_stage)
        rows = conn.execute(
            f"UPDATE ingest_queue SET status = 'pending', "
            f"error = NULL, "
            f"claimed_by = NULL, heartbeat_ts = NULL, "
            f"{stage_update}"
            f"retry_count = retry_count + 1, updated_at = datetime('now') "
            f"WHERE id IN ({placeholders}) AND status IN ('done', 'failed', 'cancelled') "
            f"AND claimed_by IS NULL "
            f"RETURNING id, file_path, doc_id",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

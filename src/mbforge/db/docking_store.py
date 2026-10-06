"""SQLite data access for docking: receptors, jobs and poses.

The persistence layer owns the SQL; callers reach it through the
``DockingRepository`` port. Job rows store ``params``/``box``/``ligands`` as
JSON text so the docking parameters can evolve without a schema change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager

_RECEPTOR_COLUMNS = (
    "receptor_id",
    "name",
    "source_filename",
    "pdbqt_path",
    "file_hash",
    "chain",
    "meta",
    "created_at",
)
_JOB_COLUMNS = (
    "job_id",
    "receptor_id",
    "engine",
    "params",
    "box",
    "ligands",
    "status",
    "progress",
    "message",
    "error",
    "created_at",
    "started_at",
    "finished_at",
)
_POSE_COLUMNS = (
    "pose_id",
    "job_id",
    "mol_id",
    "ligand_label",
    "affinity",
    "rmsd_lb",
    "rmsd_ub",
    "rank",
    "pose_path",
    "created_at",
)

_JSON_COLUMNS = {"meta", "params", "box", "ligands"}


def _decode(row: Any) -> dict[str, Any]:
    """Project a row to a JSON-friendly dict, parsing JSON columns."""
    item = dict(row)
    for key in _JSON_COLUMNS:
        if key in item and isinstance(item[key], str):
            try:
                item[key] = json.loads(item[key])
            except (json.JSONDecodeError, TypeError):
                item[key] = {} if key in ("meta", "params", "box") else []
    return item


def _dumps(value: Any, default: Any) -> str:
    return json.dumps(value if value is not None else default, ensure_ascii=False)


# ── Receptors ──────────────────────────────────────────────────────────


def insert_receptor(library_root: str | Path, receptor: dict[str, Any]) -> None:
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (conn, _):
        conn.execute(
            f"INSERT OR REPLACE INTO receptors ({', '.join(_RECEPTOR_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _RECEPTOR_COLUMNS)})",
            tuple(
                _dumps(receptor.get(column), {})
                if column in _JSON_COLUMNS
                else receptor.get(column)
                for column in _RECEPTOR_COLUMNS
            ),
        )


def list_receptors(library_root: str | Path) -> list[dict[str, Any]]:
    db = DatabaseManager.get(str(library_root))
    with db.kb_conn() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_RECEPTOR_COLUMNS)} FROM receptors "
            "ORDER BY created_at DESC, receptor_id"
        ).fetchall()
    return [_decode(row) for row in rows]


def get_receptor(library_root: str | Path, receptor_id: str) -> dict[str, Any] | None:
    db = DatabaseManager.get(str(library_root))
    with db.kb_conn() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_RECEPTOR_COLUMNS)} FROM receptors WHERE receptor_id = ?",
            (receptor_id,),
        ).fetchone()
    return _decode(row) if row is not None else None


def delete_receptor(library_root: str | Path, receptor_id: str) -> int:
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (conn, _):
        cursor = conn.execute(
            "DELETE FROM receptors WHERE receptor_id = ?", (receptor_id,)
        )
        return cursor.rowcount


# ── Jobs ───────────────────────────────────────────────────────────────


def insert_job(library_root: str | Path, job: dict[str, Any]) -> None:
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (conn, _):
        conn.execute(
            f"INSERT OR REPLACE INTO docking_jobs ({', '.join(_JOB_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _JOB_COLUMNS)})",
            tuple(
                _dumps(job.get(column), {} if column in ("params", "box") else [])
                if column in _JSON_COLUMNS
                else job.get(column)
                for column in _JOB_COLUMNS
            ),
        )


def get_job(library_root: str | Path, job_id: str) -> dict[str, Any] | None:
    db = DatabaseManager.get(str(library_root))
    with db.kb_conn() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM docking_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return _decode(row) if row is not None else None


def list_jobs(
    library_root: str | Path, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    db = DatabaseManager.get(str(library_root))
    where = "WHERE status = ?" if status else ""
    params: tuple[Any, ...] = (status, limit) if status else (limit,)
    with db.kb_conn() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM docking_jobs {where} "
            "ORDER BY created_at DESC, job_id LIMIT ?",
            params,
        ).fetchall()
    return [_decode(row) for row in rows]


def claim_next_pending(library_root: str | Path, worker: str) -> dict[str, Any] | None:
    """Atomically claim the oldest pending job, or return ``None``."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (conn, _):
        row = conn.execute(
            """
            UPDATE docking_jobs
            SET status = 'running', started_at = datetime('now'), error = NULL
            WHERE job_id = (
                SELECT job_id FROM docking_jobs WHERE status = 'pending'
                ORDER BY created_at ASC LIMIT 1
            ) AND status = 'pending'
            RETURNING *
            """
        ).fetchone()
    return _decode(row) if row is not None else None


def set_job_status(
    library_root: str | Path,
    job_id: str,
    status: str,
    *,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (conn, _):
        conn.execute(
            "UPDATE docking_jobs SET status = ?, "
            "progress = COALESCE(?, progress), "
            "message = COALESCE(?, message), "
            "error = ?, "
            "finished_at = CASE WHEN ? THEN datetime('now') ELSE finished_at END "
            "WHERE job_id = ?",
            (status, progress, message, error, 1 if finished else 0, job_id),
        )


def reset_running_jobs(library_root: str | Path) -> int:
    """Return ``running`` jobs to ``pending`` (startup recovery)."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (conn, _):
        cursor = conn.execute(
            "UPDATE docking_jobs SET status = 'pending' WHERE status = 'running'"
        )
        return cursor.rowcount


# ── Poses ──────────────────────────────────────────────────────────────


def insert_pose(library_root: str | Path, pose: dict[str, Any]) -> None:
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (conn, _):
        conn.execute(
            f"INSERT OR REPLACE INTO docking_poses ({', '.join(_POSE_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _POSE_COLUMNS)})",
            tuple(pose.get(column) for column in _POSE_COLUMNS),
        )


def list_poses(library_root: str | Path, job_id: str) -> list[dict[str, Any]]:
    db = DatabaseManager.get(str(library_root))
    with db.kb_conn() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_POSE_COLUMNS)} FROM docking_poses WHERE job_id = ? "
            "ORDER BY affinity IS NULL, affinity ASC, rank ASC",
            (job_id,),
        ).fetchall()
    return [_decode(row) for row in rows]


def get_pose(library_root: str | Path, pose_id: str) -> dict[str, Any] | None:
    db = DatabaseManager.get(str(library_root))
    with db.kb_conn() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_POSE_COLUMNS)} FROM docking_poses WHERE pose_id = ?",
            (pose_id,),
        ).fetchone()
    return _decode(row) if row is not None else None


__all__ = [
    "claim_next_pending",
    "delete_receptor",
    "get_job",
    "get_pose",
    "get_receptor",
    "insert_job",
    "insert_pose",
    "insert_receptor",
    "list_jobs",
    "list_poses",
    "list_receptors",
    "reset_running_jobs",
    "set_job_status",
]

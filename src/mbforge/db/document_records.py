"""SQLite data access for library document records.

Documents live in the library database (``documents``) keyed by the SHA-256 of
their bytes, so identical content maps to exactly one row — the primary key *is*
the content address. ``file_name`` is UNIQUE, so two documents may not share a
name; that constraint replaces the filename scan the JSON store used to need.

The stored PDF itself stays on disk at ``storage/{doc_id}/{file_name}``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager

_COLUMNS = "doc_id, file_name, title, page_count, status, created_at"


def _status_clause(statuses: Sequence[str] | None) -> tuple[str, tuple[str, ...]]:
    """Build the optional ``status IN (…)`` filter for list/count queries."""
    if not statuses:
        return "", ()
    placeholders = ",".join("?" for _ in statuses)
    return f" WHERE status IN ({placeholders})", tuple(statuses)


def insert(library_root: str | Path, record: dict[str, Any]) -> None:
    """Insert a document row.

    Raises:
        ConflictError: if ``file_name`` is already registered. A ``doc_id``
            clash is not an error — it means the same bytes are already stored.
    """
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        try:
            kb.execute(
                f"INSERT INTO documents ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record["doc_id"],
                    record["file_name"],
                    record.get("title", ""),
                    int(record.get("page_count", 0)),
                    record.get("status", "pending"),
                    record["created_at"],
                ),
            )
        except sqlite3.IntegrityError as exc:
            _raise_conflict(kb, record, exc)


def _raise_conflict(kb: Any, record: dict[str, Any], exc: Exception) -> None:
    """Turn a UNIQUE violation into the duplicate-name error the API reports."""
    from mbforge.domain.document import DuplicateDocumentNameError

    taken = kb.execute(
        "SELECT doc_id FROM documents WHERE file_name = ?", (record["file_name"],)
    ).fetchone()
    if taken is not None and taken["doc_id"] != record["doc_id"]:
        raise DuplicateDocumentNameError(
            f"A PDF named {record['file_name']!r} already exists in the library",
            detail=record["file_name"],
        ) from exc
    raise exc


def get(library_root: str | Path, doc_id: str) -> dict[str, Any] | None:
    """Return one document row, or ``None`` when it is not registered."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        row = kb.execute(
            f"SELECT {_COLUMNS} FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def find_by_filename(library_root: str | Path, file_name: str) -> dict[str, Any] | None:
    """Return the document registered under *file_name*, or ``None``."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        row = kb.execute(
            f"SELECT {_COLUMNS} FROM documents WHERE file_name = ?", (file_name,)
        ).fetchone()
    return dict(row) if row is not None else None


def list_rows(
    library_root: str | Path, *, statuses: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    """Return document rows, newest first.

    *statuses* restricts the result to those statuses; ``None`` returns every
    registered row (including ones mid-processing).
    """
    where, params = _status_clause(statuses)
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        rows = kb.execute(
            f"SELECT {_COLUMNS} FROM documents{where} ORDER BY created_at DESC, doc_id",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def count(library_root: str | Path, *, statuses: Sequence[str] | None = None) -> int:
    """Return the number of registered documents, optionally status-filtered."""
    where, params = _status_clause(statuses)
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        row = kb.execute(
            f"SELECT COUNT(*) AS cnt FROM documents{where}", params
        ).fetchone()
    return int(row["cnt"]) if row is not None else 0


def update_status(library_root: str | Path, doc_id: str, status: str) -> None:
    """Overwrite one document's status (no-op when the row is absent)."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        kb.execute("UPDATE documents SET status = ? WHERE doc_id = ?", (status, doc_id))


def delete_many(library_root: str | Path, doc_ids: Sequence[str]) -> None:
    """Remove document rows in one transaction (idempotent).

    Follows ``delete_molecule_records``: chunk the ``IN (…)`` list so a large
    selection does not exceed SQLite's ``SQLITE_MAX_VARIABLE_NUMBER``.
    """
    ids = [doc_id for doc_id in dict.fromkeys(doc_ids) if doc_id]
    if not ids:
        return
    chunk_size = 500
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        for start in range(0, len(ids), chunk_size):
            chunk = ids[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            kb.execute(
                f"DELETE FROM documents WHERE doc_id IN ({placeholders})", chunk
            )


__all__ = [
    "count",
    "delete_many",
    "find_by_filename",
    "get",
    "insert",
    "list_rows",
    "update_status",
]

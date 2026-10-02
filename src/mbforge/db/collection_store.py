"""SQLite data access for user collections ("Groups").

Collections live in the library database (``collections`` +
``collection_documents``): a collection references a ``doc_id`` by application
contract, not a foreign key, so a collection outlives any single document row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.foundation.errors import NotFoundError, ValidationError


def create(
    library_root: str | Path,
    collection_id: str,
    name: str,
    parent_id: str | None = None,
) -> None:
    """Insert a collection, validating an optional parent first."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        if parent_id:
            if parent_id == collection_id:
                raise ValidationError("a collection cannot be its own parent")
            parent = kb.execute(
                "SELECT 1 FROM collections WHERE collection_id = ?", (parent_id,)
            ).fetchone()
            if parent is None:
                raise NotFoundError("parent collection not found")
        kb.execute(
            "INSERT INTO collections (collection_id, name, parent_id) VALUES (?, ?, ?)",
            (collection_id, name, parent_id),
        )


def rename(library_root: str | Path, collection_id: str, name: str) -> None:
    """Rename a collection; raise ``NotFoundError`` when it does not exist."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        exists = kb.execute(
            "SELECT 1 FROM collections WHERE collection_id = ?", (collection_id,)
        ).fetchone()
        if exists is None:
            raise NotFoundError("collection not found")
        kb.execute(
            "UPDATE collections SET name = ? WHERE collection_id = ?",
            (name, collection_id),
        )


def list_rows(library_root: str | Path) -> list[dict[str, Any]]:
    """Return the collection rows (id, name, parent), roots-first ordering keys."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        rows = kb.execute(
            "SELECT collection_id, name, parent_id FROM collections "
            "ORDER BY created_at, collection_id"
        ).fetchall()
    return [dict(row) for row in rows]


def counts(library_root: str | Path) -> dict[str, int]:
    """Return ``{collection_id: document_count}``."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        rows = kb.execute(
            "SELECT collection_id, COUNT(*) AS cnt FROM collection_documents "
            "GROUP BY collection_id"
        ).fetchall()
    return {row["collection_id"]: row["cnt"] for row in rows}


def _delete_subtree(conn: Any, collection_id: str) -> None:
    """Delete a collection and recursively all of its descendants."""
    children = conn.execute(
        "SELECT collection_id FROM collections WHERE parent_id = ?",
        (collection_id,),
    ).fetchall()
    for child in children:
        _delete_subtree(conn, child["collection_id"])
    conn.execute(
        "DELETE FROM collection_documents WHERE collection_id = ?", (collection_id,)
    )
    conn.execute("DELETE FROM collections WHERE collection_id = ?", (collection_id,))


def delete(library_root: str | Path, collection_id: str) -> None:
    """Delete a collection and its descendants (matches the group UI)."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        exists = kb.execute(
            "SELECT 1 FROM collections WHERE collection_id = ?", (collection_id,)
        ).fetchone()
        if exists is None:
            raise NotFoundError("collection not found")
        _delete_subtree(kb, collection_id)


def add_document(library_root: str | Path, collection_id: str, doc_id: str) -> None:
    """Attach an existing document to a collection (idempotent)."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        exists = kb.execute(
            "SELECT 1 FROM collections WHERE collection_id = ?", (collection_id,)
        ).fetchone()
        if exists is None:
            raise NotFoundError("collection not found")
        kb.execute(
            "INSERT OR IGNORE INTO collection_documents (collection_id, doc_id) "
            "VALUES (?, ?)",
            (collection_id, doc_id),
        )


def remove_document(library_root: str | Path, collection_id: str, doc_id: str) -> None:
    """Detach a document from a collection (idempotent, no-op if absent)."""
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (kb, _):
        exists = kb.execute(
            "SELECT 1 FROM collections WHERE collection_id = ?", (collection_id,)
        ).fetchone()
        if exists is None:
            raise NotFoundError("collection not found")
        kb.execute(
            "DELETE FROM collection_documents WHERE collection_id = ? AND doc_id = ?",
            (collection_id, doc_id),
        )


__all__ = [
    "add_document",
    "counts",
    "create",
    "delete",
    "list_rows",
    "remove_document",
    "rename",
]

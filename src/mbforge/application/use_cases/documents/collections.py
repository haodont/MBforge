"""Collection ("Groups") management backed by SQLite.

Collections are user-defined folders that group on-disk documents. They live
in the library database (``collections`` + ``collection_documents`` tables)
deliberately separate from the JSON document store: a collection references a
``doc_id`` by application contract, not by a foreign key, so documents can be
added/removed without touching their on-disk records.
"""

from __future__ import annotations

import uuid

from mbforge.application.ports import get_database, get_repositories
from mbforge.foundation.errors import NotFoundError, ValidationError

_NAME_MAX = 200


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValidationError("collection name is required")
    if len(cleaned) > _NAME_MAX:
        raise ValidationError(
            f"collection name must be {_NAME_MAX} characters or fewer"
        )
    return cleaned


def create_collection(
    library_root: str, name: str, parent_id: str | None = None
) -> dict[str, object]:
    """Create a collection (optionally nested), returning its summary."""
    clean_name = _clean_name(name)
    db = get_database(library_root)
    collection_id = uuid.uuid4().hex
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
            (collection_id, clean_name, parent_id),
        )
    return {
        "collection_id": collection_id,
        "name": clean_name,
        "parent_id": parent_id,
        "doc_count": 0,
    }


def rename_collection(library_root: str, collection_id: str, name: str) -> None:
    clean_name = _clean_name(name)
    db = get_database(library_root)
    with db.transaction() as (kb, _):
        exists = kb.execute(
            "SELECT 1 FROM collections WHERE collection_id = ?", (collection_id,)
        ).fetchone()
        if exists is None:
            raise NotFoundError("collection not found")
        kb.execute(
            "UPDATE collections SET name = ? WHERE collection_id = ?",
            (clean_name, collection_id),
        )


def list_collections(library_root: str) -> list[dict[str, object]]:
    """Return all collections as a nested tree (roots first)."""
    db = get_database(library_root)
    with db.transaction() as (kb, _):
        rows = kb.execute(
            "SELECT collection_id, name, parent_id FROM collections "
            "ORDER BY created_at, collection_id"
        ).fetchall()
        counts = {
            row["collection_id"]: row["cnt"]
            for row in kb.execute(
                "SELECT collection_id, COUNT(*) AS cnt FROM collection_documents "
                "GROUP BY collection_id"
            ).fetchall()
        }
    nodes: dict[str, dict[str, object]] = {
        row["collection_id"]: {
            "collection_id": row["collection_id"],
            "name": row["name"],
            "parent_id": row["parent_id"],
            "doc_count": counts.get(row["collection_id"], 0),
            "children": [],
        }
        for row in rows
    }
    roots: list[dict[str, object]] = []
    for node in nodes.values():
        parent_id = node["parent_id"]
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)  # type: ignore[arg-type]
        else:
            roots.append(node)
    return roots


def _delete_subtree(conn, collection_id: str) -> None:
    """Delete a collection and recursively all of its descendants."""
    children = conn.execute(
        "SELECT collection_id FROM collections WHERE parent_id = ?",
        (collection_id,),
    ).fetchall()
    for child in children:
        _delete_subtree(conn, child["collection_id"])
    conn.execute(
        "DELETE FROM collection_documents WHERE collection_id = ?",
        (collection_id,),
    )
    conn.execute("DELETE FROM collections WHERE collection_id = ?", (collection_id,))


def delete_collection(library_root: str, collection_id: str) -> None:
    """Delete a collection and its descendants (matches the group UI)."""
    db = get_database(library_root)
    with db.transaction() as (kb, _):
        exists = kb.execute(
            "SELECT 1 FROM collections WHERE collection_id = ?", (collection_id,)
        ).fetchone()
        if exists is None:
            raise NotFoundError("collection not found")
        _delete_subtree(kb, collection_id)


def add_document(library_root: str, collection_id: str, doc_id: str) -> None:
    """Attach an existing document to a collection (idempotent)."""
    if not doc_id:
        raise ValidationError("doc_id is required")
    if (
        get_repositories(library_root).artifacts.load_document(doc_id, library_root)
        is None
    ):
        raise NotFoundError("document not found")
    db = get_database(library_root)
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


def remove_document(library_root: str, collection_id: str, doc_id: str) -> None:
    """Detach a document from a collection (idempotent, no-op if absent)."""
    db = get_database(library_root)
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

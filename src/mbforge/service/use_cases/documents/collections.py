"""Collection ("Groups") management.

Collections are user-defined folders that group on-disk documents. They live in
the library database (``collections`` + ``collection_documents`` tables): a
collection references a ``doc_id`` by application contract, not by a foreign
key, so a collection can outlive any single document row.

The persistence layer owns the SQL; this module validates inputs and builds the
collection tree.
"""

from __future__ import annotations

import uuid

from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.service.ports import get_repositories

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
    collection_id = uuid.uuid4().hex
    get_repositories(library_root).collections.create(
        collection_id, clean_name, parent_id
    )
    return {
        "collection_id": collection_id,
        "name": clean_name,
        "parent_id": parent_id,
        "doc_count": 0,
    }


def rename_collection(library_root: str, collection_id: str, name: str) -> None:
    clean_name = _clean_name(name)
    get_repositories(library_root).collections.rename(collection_id, clean_name)


def list_collections(library_root: str) -> list[dict[str, object]]:
    """Return all collections as a nested tree (roots first)."""
    repository = get_repositories(library_root).collections
    rows = repository.list_rows()
    counts = repository.counts()
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


def delete_collection(library_root: str, collection_id: str) -> None:
    """Delete a collection and its descendants (matches the group UI)."""
    get_repositories(library_root).collections.delete(collection_id)


def add_document(library_root: str, collection_id: str, doc_id: str) -> None:
    """Attach an existing document to a collection (idempotent)."""
    if not doc_id:
        raise ValidationError("doc_id is required")
    repository = get_repositories(library_root)
    if repository.documents.get(doc_id) is None:
        raise NotFoundError("document not found")
    repository.collections.add_document(collection_id, doc_id)


def remove_document(library_root: str, collection_id: str, doc_id: str) -> None:
    """Detach a document from a collection (idempotent, no-op if absent)."""
    get_repositories(library_root).collections.remove_document(collection_id, doc_id)

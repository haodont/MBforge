"""SQLite data access for the unified review queue.

Owns the ``review_items`` queue reads, the review-decision audit trail, and the
queue-clearing deletes.  Connection ownership stays with the caller (the
service/repository layer opens one connection and threads it through), matching
the existing review repository boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.domain.review import ReviewNotFoundError
from mbforge.foundation.files import safe_json_loads

_QUEUE_SQL = """
SELECT item_id AS id, kind, doc_id, page,
       bbox_x0, bbox_y0, bbox_x1, bbox_y1, crop_relpath,
       smiles, name, confidence, reasons, context_text, status,
       payload, created_at, resolved_at
FROM review_items
"""


def _decode_json(value: str | None, fallback: Any) -> Any:
    return safe_json_loads(value, fallback)


def _row_to_item(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "doc_id": row["doc_id"],
        "page": row["page"],
        "bbox": [
            row["bbox_x0"],
            row["bbox_y0"],
            row["bbox_x1"],
            row["bbox_y1"],
        ]
        if row["bbox_x0"] is not None
        else None,
        "crop_relpath": row["crop_relpath"],
        "smiles": row["smiles"],
        "name": row["name"],
        "confidence": row["confidence"],
        "reasons": _decode_json(row["reasons"], []),
        "context_text": row["context_text"],
        "status": row["status"],
        "payload": _decode_json(row["payload"], {}),
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def list_queue(
    conn: Any,
    *,
    kind: str | None = None,
    status: str | None = None,
    doc_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return a paginated queue and its unpaged total."""
    clauses = ["1=1"]
    params: list[Any] = []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if doc_id:
        clauses.append("doc_id = ?")
        params.append(doc_id)
    queue = f"SELECT * FROM ({_QUEUE_SQL}) AS unified WHERE {' AND '.join(clauses)}"
    total = int(conn.execute(f"SELECT COUNT(*) FROM ({queue})", params).fetchone()[0])
    rows = conn.execute(
        f"{queue} ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    return [_row_to_item(row) for row in rows], total


def get_item(conn: Any, kind: str, item_id: str) -> dict[str, Any]:
    items, _ = list_queue(conn, kind=kind, page=1, page_size=100000)
    for item in items:
        if item["id"] == item_id:
            return item
    raise ReviewNotFoundError(item_id)


def stats(conn: Any, doc_id: str | None = None) -> dict[str, Any]:
    """Count the unified queue, optionally scoped to one document.

    ``doc_id`` uses the same filter as :func:`list_queue`, so a caller that
    pages one document's queue can report that document's counts instead of
    the library-wide ones.
    """
    params: list[Any] = []
    where = ""
    if doc_id:
        where = " WHERE doc_id = ?"
        params.append(doc_id)
    rows = conn.execute(
        f"""
        SELECT kind, status, COUNT(*) AS count
        FROM ({_QUEUE_SQL}) AS unified{where}
        GROUP BY kind, status
        ORDER BY kind, status
        """,
        params,
    ).fetchall()
    return {
        "items": [
            {"kind": row["kind"], "status": row["status"], "count": row["count"]}
            for row in rows
        ],
        "pending": sum(row["count"] for row in rows if row["status"] == "pending"),
    }


def history(conn: Any, entity_id: str) -> tuple[str, list[dict[str, Any]]]:
    row = conn.execute(
        "SELECT entity_type FROM markush_decisions WHERE entity_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (entity_id,),
    ).fetchone()
    entity_type = row[0] if row else "review_item"
    rows = conn.execute(
        """
        SELECT decision_id, entity_type, entity_id, action,
               previous_state, new_state, reason, snapshot, created_at
        FROM markush_decisions
        WHERE entity_id = ?
        ORDER BY created_at ASC, decision_id ASC
        """,
        (entity_id,),
    ).fetchall()
    result = []
    for item in rows:
        payload = dict(item)
        payload["snapshot"] = _decode_json(payload["snapshot"], {})
        result.append(payload)
    return entity_type, result


def review_item_status_payload(
    conn: Any, item_id: str, kind: str
) -> dict[str, Any] | None:
    """Return ``{"status", "payload"}`` for a native review item, or ``None``."""
    row = conn.execute(
        "SELECT status, payload FROM review_items WHERE item_id = ? AND kind = ?",
        (item_id, kind),
    ).fetchone()
    if row is None:
        return None
    return {"status": row["status"], "payload": _decode_json(row["payload"], {})}


def set_review_item_status(conn: Any, item_id: str, kind: str, new_status: str) -> None:
    conn.execute(
        "UPDATE review_items SET status = ?, resolved_at = CASE WHEN ? = 'pending' "
        "THEN NULL ELSE datetime('now') END WHERE item_id = ? AND kind = ?",
        (new_status, new_status, item_id, kind),
    )


def set_molecule_review_status(conn: Any, mol_id: str, status: str) -> None:
    conn.execute(
        "UPDATE molecules SET review_status = ? WHERE mol_id = ?",
        (status, mol_id),
    )


def set_molecule_name(conn: Any, mol_id: str, name: str) -> None:
    conn.execute(
        "UPDATE molecules SET name = ? WHERE mol_id = ?",
        (name, mol_id),
    )


def clear_all(conn: Any) -> dict[str, int]:
    """Delete every review queue row and its audit trail on ``conn``."""
    item_ids = [
        row[0] for row in conn.execute("SELECT item_id FROM review_items").fetchall()
    ]
    conn.execute("DELETE FROM review_items")
    if item_ids:
        placeholders = ",".join("?" for _ in item_ids)
        conn.execute(
            "DELETE FROM markush_decisions WHERE entity_type = 'review_item' "
            f"AND entity_id IN ({placeholders})",
            item_ids,
        )
    return {"deleted_items": len(item_ids)}


__all__ = [
    "clear_all",
    "get_item",
    "history",
    "list_queue",
    "review_item_status_payload",
    "set_molecule_name",
    "set_molecule_review_status",
    "set_review_item_status",
    "stats",
]


def resolve_bound_designations(
    conn: Any, doc_id: str, measurement_ids: Sequence[str]
) -> int:
    """Close pending ``designation_unbound`` items whose reading now has an owner.

    The queue is a set of questions. A later pass can answer one of them — the
    example-label fallback bound thirty ``实施例…`` readings in CN120943813A —
    and an answered question left pending makes a human adjudicate a link that
    already exists. Only items whose reading is bound are closed; a reading that
    stopped being queued for another reason (its section drew nothing) keeps its
    item, because no structure was found for it.
    """
    ids = [item for item in dict.fromkeys(measurement_ids) if item]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(
        f"""
        UPDATE review_items
           SET status = 'confirmed',
               resolved_at = datetime('now')
         WHERE kind = 'designation_unbound'
           AND status = 'pending'
           AND doc_id = ?
           AND json_extract(payload, '$.measurement_id') IN ({placeholders})
        """,
        [doc_id, *ids],
    )
    return int(cursor.rowcount or 0)

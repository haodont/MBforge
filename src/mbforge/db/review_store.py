"""SQLite data access for the unified review queue.

Owns the ``review_items`` view that UNIONs native and Markush review candidates,
the review-decision audit trail, and the queue-clearing deletes.  Connection
ownership stays with the caller (the service/repository layer opens one
connection and threads it through), matching the existing review repository
boundary.
"""

from __future__ import annotations

from typing import Any

from mbforge.domain.review import ReviewNotFoundError
from mbforge.foundation.files import safe_json_loads

_QUEUE_SQL = """
SELECT item_id AS id, kind, doc_id, page,
       bbox_x0, bbox_y0, bbox_x1, bbox_y1, crop_relpath,
       smiles, name, confidence, reasons, context_text, status,
       payload, created_at, resolved_at
FROM review_items
UNION ALL
SELECT candidate_id AS id, 'markush_link' AS kind, doc_id,
       CASE WHEN page IS NULL THEN NULL ELSE page + 1 END AS page,
       bbox_x0, bbox_y0, bbox_x1, bbox_y1, crop_relpath,
       smiles, name, composite_confidence AS confidence, reasons,
       context_text, review_status AS status, properties AS payload,
       created_at, superseded_at AS resolved_at
FROM markush_review_candidates
WHERE superseded_at IS NULL
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


def stats(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        f"""
        SELECT kind, status, COUNT(*) AS count
        FROM ({_QUEUE_SQL}) AS unified
        GROUP BY kind, status
        ORDER BY kind, status
        """
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


def markush_candidate_version(conn: Any, item_id: str) -> int | None:
    """Return the review version of a Markush review candidate, or ``None``."""
    row = conn.execute(
        "SELECT review_version FROM markush_review_candidates WHERE candidate_id = ?",
        (item_id,),
    ).fetchone()
    return int(row[0]) if row is not None else None


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
    candidate_ids = [
        row[0]
        for row in conn.execute(
            "SELECT candidate_id FROM markush_review_candidates"
        ).fetchall()
    ]

    def _delete_audit(entity_type: str, entity_ids: list[str]) -> None:
        if not entity_ids:
            return
        placeholders = ",".join("?" for _ in entity_ids)
        conn.execute(
            "DELETE FROM markush_decisions WHERE entity_type = ? "
            f"AND entity_id IN ({placeholders})",
            [entity_type, *entity_ids],
        )

    conn.execute("DELETE FROM review_items")
    _delete_audit("review_item", item_ids)
    conn.execute("DELETE FROM markush_review_candidates")
    _delete_audit("review_candidate", candidate_ids)
    return {"deleted_items": len(item_ids), "deleted_candidates": len(candidate_ids)}


__all__ = [
    "clear_all",
    "get_item",
    "history",
    "list_queue",
    "markush_candidate_version",
    "review_item_status_payload",
    "set_molecule_name",
    "set_molecule_review_status",
    "set_review_item_status",
    "stats",
]

"""Unified review queue service across native and Markush review records.

Sits above ``ReviewLifecycle`` and ``MarkushReview`` to present a single
queue surface for the HTTP router and review UI. Owns the ``review_items``
view that UNIONs native and Markush candidates so the frontend does not
need to query two tables.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..core.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
    resolve_status_transition,
)
from ..models.review import (
    ReviewDecisionResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
)
from ..storage.review_audit import (
    insert_review_item,  # noqa: F401 — re-exported for pipeline callers
    record_review_decision,
)
from ..utils.files import safe_json_loads
from ..utils.logger import get_logger
from .markush.review import apply_decision

logger = get_logger(__name__)

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


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
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
    conn: sqlite3.Connection,
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


def get_item(conn: sqlite3.Connection, kind: str, item_id: str) -> dict[str, Any]:
    items, _ = list_queue(conn, kind=kind, page=1, page_size=100000)
    for item in items:
        if item["id"] == item_id:
            return item
    raise ReviewNotFoundError(item_id)


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
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


def history(
    conn: sqlite3.Connection, entity_id: str
) -> tuple[str, list[dict[str, Any]]]:
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


def decide(
    conn: sqlite3.Connection,
    *,
    kind: str,
    item_id: str,
    action: str,
    reason: str = "",
    choice: str | None = None,
) -> dict[str, Any]:
    """Route one decision to its native persistence target."""
    if kind == "markush_link":
        row = conn.execute(
            "SELECT review_version FROM markush_review_candidates WHERE candidate_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ReviewNotFoundError(item_id)
        mapped_action = {
            "confirm": "confirm_complete",
            "reject": "reject",
            "reopen": "reopen",
        }.get(action)
        if mapped_action is None:
            raise ReviewTransitionError(f"unsupported action: {action}")
        return apply_decision(
            conn,
            candidate_id=item_id,
            expected_version=int(row[0]),
            action=mapped_action,
            reason=reason,
        )

    row = conn.execute(
        "SELECT status, payload FROM review_items WHERE item_id = ? AND kind = ?",
        (item_id, kind),
    ).fetchone()
    if row is None:
        raise ReviewNotFoundError(item_id)
    current = row["status"]
    new_status = resolve_status_transition(
        current,
        action,
        action_targets={"confirm": "confirmed", "reject": "rejected"},
    )
    conn.execute(
        "UPDATE review_items SET status = ?, resolved_at = CASE WHEN ? = 'pending' "
        "THEN NULL ELSE datetime('now') END WHERE item_id = ? AND kind = ?",
        (new_status, new_status, item_id, kind),
    )
    payload = _decode_json(row["payload"], {})
    mol_id = payload.get("mol_id") if isinstance(payload, dict) else None
    if mol_id and kind == "low_conf_molecule":
        conn.execute(
            "UPDATE molecules SET review_status = ? WHERE mol_id = ?",
            (new_status, mol_id),
        )
    if kind == "ambiguous_coref" and new_status == "confirmed":
        # Adopt the reviewer-chosen compound identifier as the molecule name
        # (falls back to the OCR suggestion, then the first label).
        labels = payload.get("ocr_labels") if isinstance(payload, dict) else None
        chosen = (
            choice
            or (payload.get("coref_primary") if isinstance(payload, dict) else None)
            or (labels[0] if isinstance(labels, list) and labels else None)
        )
        if mol_id and chosen:
            conn.execute(
                "UPDATE molecules SET name = ? WHERE mol_id = ?",
                (str(chosen), mol_id),
            )
    record_review_decision(
        conn,
        entity_type="review_item",
        entity_id=item_id,
        action=action,
        previous_state=current,
        new_state=new_status,
        reason=reason,
        snapshot=payload,
    )
    return {"id": item_id, "kind": kind, "status": new_status}


def _get_db(library_root: str | None):
    from ..storage.layout import resolve_library_root
    from ..storage.sqlite.database import DatabaseManager

    return DatabaseManager.get(str(resolve_library_root(library_root)))


def queue_page(
    library_root: str | None,
    kind: str | None,
    item_status: str | None,
    doc_id: str | None,
    page: int,
    page_size: int,
) -> ReviewQueueResponse:
    db = _get_db(library_root)
    with db.mol_conn() as conn:
        items, total = list_queue(
            conn,
            kind=kind,
            status=item_status,
            doc_id=doc_id,
            page=page,
            page_size=page_size,
        )
    return ReviewQueueResponse(
        items=[ReviewQueueItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def stats_summary(library_root: str | None) -> dict[str, Any]:
    db = _get_db(library_root)
    with db.mol_conn() as conn:
        return stats(conn)


def item_detail(library_root: str | None, kind: str, item_id: str) -> dict[str, Any]:
    db = _get_db(library_root)
    with db.mol_conn() as conn:
        return get_item(conn, kind, item_id)


def decide_items(
    library_root: str | None,
    action: str,
    reason: str | None,
    items: list[Any],
) -> ReviewDecisionResponse:
    """Apply one action to a batch of review items.

    *items* are request-shaped objects exposing ``kind``, ``id`` and an
    optional ``choice`` attribute.
    """
    db = _get_db(library_root)
    updated = 0
    skipped = 0
    results: list[dict] = []
    with db.mol_conn() as conn:
        for item in items:
            try:
                result = decide(
                    conn,
                    kind=item.kind,
                    item_id=item.id,
                    action=action,
                    reason=reason,
                    choice=item.choice,
                )
            except (
                ReviewConflictError,
                ReviewNotFoundError,
                ReviewTransitionError,
            ) as exc:
                skipped += 1
                results.append({"kind": item.kind, "id": item.id, "error": str(exc)})
            else:
                updated += 1
                results.append(result)
    return ReviewDecisionResponse(updated=updated, skipped=skipped, results=results)


def clear_all_review_queue(library_root: str | None) -> dict[str, int]:
    """Empty the entire review center.

    Deletes every row from ``review_items`` and ``markush_review_candidates``
    (including superseded history rows) regardless of status, plus the
    ``markush_decisions`` audit rows keyed on those entities so no orphaned
    audit trail survives.

    Confirmed/promoted artifacts are intentionally kept: ``molecules``,
    ``markush_scaffolds``/``markush_fragments`` and ``markush_evidence`` are
    ingested knowledge, not queue entries, and are re-derived or referenced
    independently of the queue.
    """
    db = _get_db(library_root)
    with db.mol_conn() as conn:
        return clear_all(conn)


def clear_all(conn: sqlite3.Connection) -> dict[str, int]:
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


def entity_history(
    library_root: str | None, entity_id: str
) -> tuple[Any, list[dict[str, Any]]]:
    db = _get_db(library_root)
    with db.mol_conn() as conn:
        return history(conn, entity_id)

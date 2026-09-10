"""Review persistence primitives (audit + queue row writes).

Writes one append-only record per reviewer action into the shared
``markush_decisions`` table using the shared review-decision contract,
plus the ``insert_review_item`` write primitive consumed by the pipeline
persist stage and the review queue service. The state machine itself
lives in :mod:`mbforge.core.review`.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from typing import Any


def record_review_decision(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    previous_state: str | None = None,
    new_state: str | None = None,
    reason: str = "",
    snapshot: Mapping[str, Any] | None = None,
) -> None:
    """Append one audit record using the shared review-decision contract."""
    conn.execute(
        """
        INSERT INTO markush_decisions
            (decision_id, entity_type, entity_id, action,
             previous_state, new_state, reason, snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex[:16],
            entity_type,
            entity_id,
            action,
            previous_state,
            new_state,
            reason,
            json.dumps(dict(snapshot or {}), ensure_ascii=False),
        ),
    )


def insert_review_item(
    conn: sqlite3.Connection,
    *,
    kind: str,
    doc_id: str | None = None,
    page: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    crop_relpath: str | None = None,
    smiles: str | None = None,
    name: str | None = None,
    confidence: float | None = None,
    reasons: list[str] | None = None,
    context_text: str | None = None,
    payload: dict[str, Any] | None = None,
    item_id: str | None = None,
) -> str:
    """Insert or replace a native review item with a stable caller id."""
    resolved_id = item_id or uuid.uuid4().hex[:16]
    conn.execute(
        """
        INSERT INTO review_items
            (item_id, kind, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
             crop_relpath, smiles, name, confidence, reasons, context_text,
             status, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        ON CONFLICT(item_id) DO UPDATE SET
            kind = excluded.kind,
            doc_id = excluded.doc_id,
            page = excluded.page,
            bbox_x0 = excluded.bbox_x0,
            bbox_y0 = excluded.bbox_y0,
            bbox_x1 = excluded.bbox_x1,
            bbox_y1 = excluded.bbox_y1,
            crop_relpath = excluded.crop_relpath,
            smiles = excluded.smiles,
            name = excluded.name,
            confidence = excluded.confidence,
            reasons = excluded.reasons,
            context_text = excluded.context_text,
            payload = excluded.payload
        """,
        (
            resolved_id,
            kind,
            doc_id,
            page,
            *(bbox or (None, None, None, None)),
            crop_relpath,
            smiles,
            name,
            confidence,
            json.dumps(reasons or [], ensure_ascii=False),
            context_text,
            json.dumps(payload or {}, ensure_ascii=False),
        ),
    )
    return resolved_id

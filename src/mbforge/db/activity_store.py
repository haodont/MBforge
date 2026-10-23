"""SQLite data access for activity review items.

The ``activities`` table is retired: activity readings live in ``measurements``
(see :mod:`mbforge.db.measurement_store`), where a reading is stored whether or
not a structure owns it. What remains here is the review-item read, which the
activity endpoint lists alongside stored readings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager


def list_activity_review_items(
    library_root: str | Path, doc_id: str, limit: int
) -> list[dict[str, Any]]:
    """Return pending activity-match review items for a document."""
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            """
            SELECT item_id, status, doc_id, page, smiles, name, confidence,
                   reasons, context_text, payload, created_at
            FROM review_items
            WHERE kind = 'activity_match' AND doc_id = ?
            ORDER BY page, created_at, item_id
            LIMIT ?
            """,
            (doc_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


__all__ = ["list_activity_review_items"]

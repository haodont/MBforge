"""SQLite access for review-center AI suggestions.

A suggestion is stored in its own table because review rows are rebuilt on every
publication while a paid model answer is not; the pair (kind, item_id) is the
key, and a re-run replaces the answer instead of duplicating it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager

_KINDS = (
    "markush_link",
    "review_required",
    "low_conf_molecule",
    "unparsable_smiles",
    "missing_evidence",
    "ambiguous_coref",
    "patent_fact_review",
    "smiles_correction",
)


def _row_to_suggestion(row: Any) -> dict[str, Any]:
    return {
        "kind": row["kind"],
        "item_id": row["item_id"],
        "status": row["status"],
        "model": row["model"] or "",
        "vision": bool(row["vision"]),
        "answer": row["answer"] or "",
        "error": row["error"] or "",
        "created_at": row["created_at"],
    }


def upsert(library_root: str | Path, suggestion: dict[str, Any]) -> None:
    """Store (or replace) one item suggestion."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.transaction() as (_kb_conn, conn):
        conn.execute(
            "INSERT INTO review_assists "
            "(kind, item_id, status, model, vision, answer, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(kind, item_id) DO UPDATE SET "
            "status = excluded.status, model = excluded.model, "
            "vision = excluded.vision, answer = excluded.answer, "
            "error = excluded.error, created_at = datetime('now')",
            (
                suggestion["kind"],
                suggestion["item_id"],
                suggestion["status"],
                suggestion.get("model", ""),
                1 if suggestion.get("vision") else 0,
                suggestion.get("answer", ""),
                suggestion.get("error", ""),
            ),
        )


def get(library_root: str | Path, kind: str, item_id: str) -> dict[str, Any] | None:
    """One stored suggestion, or ``None``."""
    db = DatabaseManager.get(str(library_root))
    row = db.execute(
        "SELECT * FROM review_assists WHERE kind = ? AND item_id = ?",
        (kind, item_id),
        db="mol",
    )
    return _row_to_suggestion(row[0]) if row else None


def for_items(
    library_root: str | Path, keys: Sequence[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Suggestions for the given (kind, item_id) pairs, keyed by the pair."""
    wanted = {(kind, item_id) for kind, item_id in keys if kind and item_id}
    if not wanted:
        return {}
    db = DatabaseManager.get(str(library_root))
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, item_id in wanted:
        row = db.execute(
            "SELECT * FROM review_assists WHERE kind = ? AND item_id = ?",
            (kind, item_id),
            db="mol",
        )
        if row:
            result[(kind, item_id)] = _row_to_suggestion(row[0])
    return result


def pending_without_suggestion(
    library_root: str | Path, *, kinds: Sequence[str], limit: int
) -> list[dict[str, str]]:
    """Pending items that have no stored suggestion yet, oldest first.

    Bounded by *limit*: every item costs one model call.
    """
    allowed = [kind for kind in kinds if kind in _KINDS] or list(_KINDS)
    db = DatabaseManager.get(str(library_root))
    placeholders = ", ".join("?" for _ in allowed)
    rows = db.execute(
        "SELECT id, kind FROM ("
        "  SELECT item_id AS id, kind FROM review_items WHERE status = 'pending'"
        "  UNION ALL"
        "  SELECT candidate_id AS id, 'markush_link' AS kind"
        "  FROM markush_review_candidates"
        "  WHERE superseded_at IS NULL AND review_status = 'pending'"
        ") AS queue "
        f"WHERE queue.kind IN ({placeholders}) "
        "AND NOT EXISTS (SELECT 1 FROM review_assists a "
        "                WHERE a.kind = queue.kind AND a.item_id = queue.id) "
        "ORDER BY queue.id LIMIT ?",
        (*allowed, limit),
        db="mol",
    )
    return [{"kind": row["kind"], "item_id": row["id"]} for row in rows]


__all__ = ["for_items", "get", "pending_without_suggestion", "upsert"]

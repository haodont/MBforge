"""SQLite data access for the ``activities`` table and activity review items."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager

# Columns projected for the public API. Keep this list tight: callers
# (notably the agent tools) serialize the result to JSON, so trimming here
# also trims the wire payload.
_ACTIVITY_COLUMNS = (
    "activity_id",
    "mol_id",
    "doc_id",
    "activity_type",
    "value",
    "value_original",
    "unit_original",
    "operator",
    "measurement_kind",
    "metric",
    "value_canonical",
    "unit_canonical",
    "operator_original",
    "scale",
    "value_text",
    "qualitative_raw",
    "qualitative_rank",
    "qualitative_scheme",
    "qualitative_label",
    "reference_raw",
    "reference_key",
    "reference_type",
    "target",
    "assay_type",
    "assay_description",
    "confidence",
    "page_num",
    "table_idx",
    "row_idx",
    "col_idx",
    "row_label",
    "row_smiles",
    "raw_text",
    "created_at",
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Project an activities row to a JSON-friendly dict."""
    keys = set(row.keys()) if hasattr(row, "keys") else set(_ACTIVITY_COLUMNS)
    return {key: row[key] for key in _ACTIVITY_COLUMNS if key in keys}


def list_activities(
    library_root: str | Path,
    doc_id: str,
    target: str = "",
    assay_description: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List activity records for a document, optionally filtered.

    Missing columns are projected as ``NULL`` so the projection works against
    older schemas; ordering keeps the agent reading in document order.
    """
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        available_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(activities)")
        }
        projection = ", ".join(
            f"{column} AS {column}"
            if column in available_columns
            else f"NULL AS {column}"
            for column in _ACTIVITY_COLUMNS
        )
        target_column = "target" if "target" in available_columns else "NULL"
        assay_description_column = (
            "assay_description" if "assay_description" in available_columns else "NULL"
        )
        assay_type_column = (
            "assay_type" if "assay_type" in available_columns else "NULL"
        )
        ordering = ", ".join(
            column if column in available_columns else "NULL"
            for column in ("page_num", "table_idx", "row_idx", "col_idx")
        )
        clauses = ["doc_id = ?"]
        params: list[Any] = [doc_id]
        if target:
            clauses.append(f"LOWER(COALESCE({target_column}, '')) LIKE ?")
            params.append(f"%{target.lower()}%")
        if assay_description:
            clauses.append(
                f"LOWER(COALESCE({assay_description_column}, {assay_type_column}, '')) LIKE ?"
            )
            params.append(f"%{assay_description.lower()}%")
        sql = (
            f"SELECT {projection} FROM activities WHERE {' AND '.join(clauses)} "
            f"ORDER BY {ordering} LIMIT ?"
        )
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


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


__all__ = ["list_activities", "list_activity_review_items"]

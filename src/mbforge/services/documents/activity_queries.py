"""Domain operations for activity data.

Read-side helpers for the ``activities`` table. Used by the agent SAR
tools and by any router that needs to surface activity data without
joining through the ``evidence`` table.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ...storage.sqlite.database import DatabaseManager
from ...utils.json_utils import safe_json_loads

# Columns selected for the public API. Keep this list tight: callers
# (notably the agent tools) serialize the result to JSON, so trimming
# here also trims the wire payload.
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


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Project an activities row to a JSON-friendly dict."""
    keys = set(row.keys()) if hasattr(row, "keys") else set(_ACTIVITY_COLUMNS)
    return {key: row[key] for key in _ACTIVITY_COLUMNS if key in keys}


def list_activities(
    library_root: str | None,
    doc_id: str,
    target: str = "",
    assay_description: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List activity records for a document, optionally filtered.

    Args:
        library_root: Project root directory.
        doc_id: Document identifier.
        target: Optional target name (case-insensitive substring match).
        assay_description: Optional assay name (case-insensitive substring
            match against ``assay_description`` or ``assay_type``).
        limit: Maximum number of rows to return (default 200).

    Returns:
        List of activity dicts, ordered by (page_num, table_idx, row_idx)
        so the agent can read the result in document order.
    """
    if not doc_id:
        return []
    with DatabaseManager.get(library_root).mol_conn() as conn:
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


def list_activity_records(
    library_root: str | None,
    doc_id: str,
    target: str = "",
    assay_description: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not doc_id:
        return []

    records = [
        {
            **record,
            "review_id": None,
            "source": "activities",
            "status": "persisted",
            "reasons": [],
        }
        for record in list_activities(
            library_root,
            doc_id,
            target=target,
            assay_description=assay_description,
            limit=limit,
        )
    ]

    with DatabaseManager.get(library_root).mol_conn() as conn:
        review_rows = conn.execute(
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

    target_lower = target.lower()
    assay_lower = assay_description.lower()
    for row in review_rows:
        payload = safe_json_loads(row["payload"], {})
        if not isinstance(payload, dict):
            continue
        row_target = str(payload.get("target") or "")
        row_assay = str(
            payload.get("assay_description") or payload.get("assay_type") or ""
        )
        if target_lower and target_lower not in row_target.lower():
            continue
        if assay_lower and assay_lower not in row_assay.lower():
            continue
        reasons = safe_json_loads(row["reasons"], [])
        if not isinstance(reasons, list):
            reasons = []
        records.append(
            {
                "activity_id": None,
                "review_id": row["item_id"],
                "source": "review_items",
                "status": row["status"],
                "mol_id": payload.get("mol_id"),
                "doc_id": row["doc_id"] or doc_id,
                "activity_type": str(payload.get("activity_type") or "IC50"),
                "value": payload.get("value"),
                "value_original": payload.get("value_original"),
                "unit_original": payload.get("unit_original"),
                "operator": payload.get("operator") or "=",
                "measurement_kind": payload.get("measurement_kind"),
                "metric": payload.get("metric"),
                "value_canonical": payload.get("value_canonical"),
                "unit_canonical": payload.get("unit_canonical"),
                "operator_original": payload.get("operator_original"),
                "scale": payload.get("scale"),
                "value_text": payload.get("value_text"),
                "qualitative_raw": payload.get("qualitative_raw"),
                "qualitative_rank": payload.get("qualitative_rank"),
                "qualitative_scheme": payload.get("qualitative_scheme"),
                "qualitative_label": payload.get("qualitative_label"),
                "reference_raw": payload.get("reference_raw"),
                "reference_key": payload.get("reference_key"),
                "reference_type": payload.get("reference_type"),
                "target": payload.get("target"),
                "assay_type": payload.get("assay_type"),
                "assay_description": payload.get("assay_description")
                or payload.get("assay_type"),
                "confidence": row["confidence"],
                "page_num": row["page"],
                "table_idx": payload.get("table_idx"),
                "row_idx": payload.get("row_idx"),
                "col_idx": payload.get("col_idx"),
                "row_label": row["name"],
                "row_smiles": row["smiles"],
                "raw_text": row["context_text"],
                "created_at": row["created_at"],
                "reasons": reasons,
            }
        )

    records.sort(
        key=lambda record: (
            record.get("page_num") if record.get("page_num") is not None else 10**9,
            record.get("table_idx") if record.get("table_idx") is not None else 10**9,
            record.get("row_idx") if record.get("row_idx") is not None else 10**9,
            record.get("col_idx") if record.get("col_idx") is not None else 10**9,
            str(record.get("activity_id") or record.get("review_id") or ""),
        )
    )
    return records[:limit]

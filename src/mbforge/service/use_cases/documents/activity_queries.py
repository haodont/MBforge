"""Domain operations for activity data.

Read-side helpers for the ``activities`` table. Used by the agent SAR
tools and by any router that needs to surface activity data without
joining through the ``evidence`` table. The persistence layer owns the SQL.
"""

from __future__ import annotations

from typing import Any

from mbforge.foundation.files import safe_json_loads
from mbforge.service.ports import get_repositories


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
    return get_repositories(library_root).activities.list_activities(
        doc_id,
        target=target,
        assay_description=assay_description,
        limit=limit,
    )


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

    review_rows = get_repositories(library_root).activities.list_activity_review_items(
        doc_id, limit
    )

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

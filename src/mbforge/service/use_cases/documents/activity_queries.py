"""Domain operations for activity data.

Read-side helpers over the ``measurements`` table. A reading is first-class
data: it is listed whether or not a structure owns it, so a document's printed
activity is never invisible just because association has not resolved.

The structure links live in ``measurement_attribution`` and are surfaced
alongside each reading, so a caller can tell "12 nM for 77-A, structure known"
from "12 nM for 77-A, structure unresolved" without a second query per row.
"""

from __future__ import annotations

from typing import Any

from mbforge.contracts.measurement import (
    MeasurementDatasetStats,
    MeasurementQuery,
)
from mbforge.service.ports import get_repositories


def list_measurements(
    library_root: str | None,
    *,
    doc_id: str = "",
    target: str = "",
    assay_description: str = "",
    evidence_grade: str = "",
    review_status: str = "",
    metric: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List printed readings, each with the structures attributed to it."""
    repositories = get_repositories(library_root)
    rows = repositories.measurements.list(
        MeasurementQuery(
            doc_id=doc_id,
            target=target,
            assay_description=assay_description,
            evidence_grade=evidence_grade,
            review_status=review_status,
            metric=metric,
            limit=limit,
        )
    )
    if not rows:
        return []
    attributions = repositories.measurements.attributions_for(
        [row["measurement_id"] for row in rows]
    )
    enriched: list[dict[str, Any]] = []
    for row in rows:
        links = attributions.get(row["measurement_id"], [])
        enriched.append(
            {
                **row,
                "attributions": links,
                "mol_ids": [link["mol_id"] for link in links],
                "attributed": bool(links),
            }
        )
    return enriched


def list_activity_records(
    library_root: str | None,
    doc_id: str,
    target: str = "",
    assay_description: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Activity records for a document, shaped for the HTTP/agent response.

    A reading is a stored measurement; there is no pending-review fallback, so
    a consumer never sees a candidate mixed into the settled readings.
    """
    if not doc_id:
        return []
    readings = list_measurements(
        library_root,
        doc_id=doc_id,
        target=target,
        assay_description=assay_description,
        limit=limit,
    )
    records: list[dict[str, Any]] = [
        {
            "activity_id": row["measurement_id"],
            "source": "measurements",
            "status": "persisted",
            "mol_id": (row["mol_ids"][0] if len(row["mol_ids"]) == 1 else None),
            "doc_id": row["doc_id"],
            "activity_type": row["activity_type"],
            "value": row["original_value"],
            "value_original": row["original_value"],
            "unit_original": row["original_unit"],
            "operator": row["operator"],
            "measurement_kind": row["measurement_kind"],
            "metric": row["metric"],
            "value_canonical": row["canonical_value"],
            "unit_canonical": row["canonical_unit"],
            "operator_original": row["provenance"].get(
                "operator_original", row["operator"]
            ),
            "scale": row["scale"],
            "value_text": row["value_text"],
            "qualitative_raw": row["qualitative_raw"],
            "qualitative_rank": row["qualitative_rank"],
            "qualitative_scheme": row["qualitative_scheme"],
            "qualitative_label": row["qualitative_label"],
            "reference_raw": row["reference_raw"],
            "reference_key": row["reference_key"],
            "reference_type": row["reference_type"],
            "target": row["target"],
            "assay_type": row["assay_type"],
            "assay_description": row["assay_description"],
            "confidence": None,
            "page_num": row["page_num"],
            "table_idx": row["table_idx"],
            "row_idx": row["row_idx"],
            "col_idx": row["col_idx"],
            "row_label": row["row_label"],
            "row_smiles": None,
            "raw_text": row["raw_text"],
            "created_at": row["created_at"],
            "evidence_grade": row["evidence_grade"],
            "review_status": row["review_status"],
            "attributed": row["attributed"],
            "mol_ids": row["mol_ids"],
            "reasons": [],
        }
        for row in readings
    ]

    records.sort(
        key=lambda record: (
            record.get("page_num") if record.get("page_num") is not None else 10**9,
            record.get("table_idx") if record.get("table_idx") is not None else 10**9,
            record.get("row_idx") if record.get("row_idx") is not None else 10**9,
            record.get("col_idx") if record.get("col_idx") is not None else 10**9,
            str(record.get("activity_id") or ""),
        )
    )
    return records[:limit]


def dataset_stats(
    library_root: str | None, doc_id: str = ""
) -> MeasurementDatasetStats:
    """Coverage counts: what the document printed vs what reached a structure.

    ``unattributed`` alone says nothing about whether the gap is fixable, so it
    is split by reason. The classification needs the artifact's entries and the
    document's detection count, which is why it happens here rather than in the
    database layer.
    """
    repositories = get_repositories(library_root)
    stats = repositories.measurements.stats(doc_id)
    rows = repositories.measurements.unattributed_readings(doc_id)

    by_reason: dict[str, int] = {}
    attached = 0
    drawn_by_doc: dict[str, set[str]] = {}
    for row in rows:
        if row.get("entry_id") or row.get("reference_key"):
            attached += 1
        if row.get("attributed_id"):
            continue
        doc = row["doc_id"]
        if doc not in drawn_by_doc:
            drawn_by_doc[doc] = repositories.measurements.document_label_numbers(doc)
        drawn = drawn_by_doc[doc]
        # Compare the full designation: ``77-A`` is not ``77``, and treating it
        # as the same number would claim a structure the document never drew.
        designation = str(row.get("reference_key") or "").strip()
        if not designation:
            reason = "no_printed_designation"
        elif not drawn:
            # No structure was detected anywhere in this document.
            reason = "document_has_no_detections"
        elif designation in drawn:
            # The document drew a structure under this very designation and still
            # no rule bound it — recoverable extraction work.
            reason = "structure_detected_unmatched"
        else:
            # Structures were drawn for other compounds; this designation has
            # none (chiral SFC/LC-MS-only entries such as 77-A / 77-B).
            reason = "designation_without_structure"
        by_reason[reason] = by_reason.get(reason, 0) + 1

    return stats.model_copy(
        update={
            "attached_to_a_designation": attached,
            "unattributed_by_reason": by_reason,
        }
    )


__all__ = ["dataset_stats", "list_activity_records", "list_measurements"]

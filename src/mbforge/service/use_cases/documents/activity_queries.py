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

#: Precedence for the attribution a reader should trust. A human decision
#: outranks the agent's adjudication, which outranks the rules'; within one
#: method an accepted link outranks a pending one.
_ATTRIBUTION_METHOD_RANK = {"human": 3, "agent": 2, "model": 2, "rule": 1}
_ATTRIBUTION_STATUS_RANK = {"accepted": 2, "pending": 1, "rejected": 0}


def effective_attribution(
    links: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The attribution a reader should trust among every link a reading carries.

    A reading may carry several candidates (a rule link and a human override, or
    a contested pair). The effective one is the highest-precedence non-rejected
    link; the rest stay on the reading for audit.
    """
    candidates = [
        link for link in links if str(link.get("review_status") or "") != "rejected"
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda link: (
            _ATTRIBUTION_METHOD_RANK.get(str(link.get("method") or ""), 0),
            _ATTRIBUTION_STATUS_RANK.get(str(link.get("review_status") or ""), 0),
        ),
    )


def list_measurements(
    library_root: str | None,
    *,
    doc_id: str = "",
    target: str = "",
    assay_description: str = "",
    evidence_grade: str = "",
    review_status: str = "",
    metric: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    offset: int = 0,
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
            min_value=min_value,
            max_value=max_value,
            offset=offset,
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
        effective = effective_attribution(links)
        enriched.append(
            {
                **row,
                "attributions": links,
                "effective_attribution": effective,
                "mol_ids": [link["mol_id"] for link in links],
                "attributed": effective is not None,
            }
        )
    return enriched


def _document_context(library_root: str | None, doc_id: str) -> dict[str, Any]:
    """Drawings and label coverage for one document, read once per document."""
    repositories = get_repositories(library_root)
    if not doc_id:
        return {"drawn": set(), "unlabeled": 0, "detections": 0, "grouped": set()}
    return {
        "drawn": repositories.measurements.document_label_numbers(doc_id),
        "unlabeled": repositories.measurements.unlabeled_structure_count(doc_id),
        "detections": repositories.measurements.document_detection_count(doc_id),
        "grouped": repositories.measurements.group_caption_designations(doc_id),
    }


def _unattributed_reason(
    designation: str,
    drawn: set[str],
    unlabeled: int,
    detections: int,
    grouped: set[str] | None = None,
) -> str:
    """Why one unattributed reading has no structure.

    The distinction is the product value: a source that never drew the compound
    and a label the pipeline never read are different facts, and only the second
    is recoverable work.
    """
    if not designation:
        return "no_printed_designation"
    if designation in drawn:
        return "structure_detected_unmatched"
    if grouped and designation in grouped:
        # A caption that names several designations at once: the document drew the
        # structures but never gives one of them for one designation.
        return "designation_group_caption"
    if detections == 0:
        return "document_has_no_detections"
    if unlabeled > 0:
        return "label_not_read"
    return "designation_without_structure"


def list_activity_records(
    library_root: str | None,
    doc_id: str,
    target: str = "",
    assay_description: str = "",
    limit: int = 200,
    *,
    metric: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Activity records for a document, shaped for the HTTP/agent response.

    A reading is a stored measurement; there is no pending-review fallback, so
    a consumer never sees a candidate mixed into the settled readings. Every
    reading is returned, including ones no structure owns; ``attributed`` and
    ``mol_ids`` say whether a molecule can be named.
    """
    if not doc_id:
        return []
    readings = list_measurements(
        library_root,
        doc_id=doc_id,
        target=target,
        assay_description=assay_description,
        metric=metric,
        min_value=min_value,
        max_value=max_value,
        offset=offset,
        limit=limit,
    )
    context = _document_context(library_root, doc_id)
    identities = get_repositories(library_root).molecules.identity_fields(
        [mol_id for row in readings for mol_id in row["mol_ids"]]
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
            "row_smiles": (
                identities.get(row["mol_ids"][0], {}).get("canonical_smiles")
                if len(row["mol_ids"]) == 1
                else None
            ),
            "molecules": [
                {
                    "mol_id": mol_id,
                    "smiles": identities.get(mol_id, {}).get("canonical_smiles"),
                    "name": identities.get(mol_id, {}).get("name"),
                }
                for mol_id in row["mol_ids"]
            ],
            "raw_text": row["raw_text"],
            "created_at": row["created_at"],
            "evidence_grade": row["evidence_grade"],
            "evidence_ids": row["evidence_ids"],
            "review_status": row["review_status"],
            "attributed": row["attributed"],
            "mol_ids": row["mol_ids"],
            "attributions": row["attributions"],
            "effective_attribution": row.get("effective_attribution"),
            "effective_mol_id": (
                (row.get("effective_attribution") or {}).get("mol_id") or None
            ),
            "reasons": (
                []
                if row["attributed"]
                else [
                    _unattributed_reason(
                        str(row.get("reference_key") or "").strip(),
                        context["drawn"],
                        context["unlabeled"],
                        context["detections"],
                        context["grouped"],
                    )
                ]
            ),
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
    context_by_doc: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("entry_id") or row.get("reference_key"):
            attached += 1
        if row.get("attributed_id"):
            continue
        doc = row["doc_id"]
        if doc not in context_by_doc:
            context_by_doc[doc] = _document_context(library_root, doc)
        context = context_by_doc[doc]
        # Compare the full designation: ``77-A`` is not ``77``, and treating it
        # as the same number would claim a structure the document never drew.
        reason = _unattributed_reason(
            str(row.get("reference_key") or "").strip(),
            context["drawn"],
            context["unlabeled"],
            context["detections"],
            context["grouped"],
        )
        by_reason[reason] = by_reason.get(reason, 0) + 1

    return stats.model_copy(
        update={
            "attached_to_a_designation": attached,
            "unattributed_by_reason": by_reason,
        }
    )


__all__ = ["dataset_stats", "list_activity_records", "list_measurements"]

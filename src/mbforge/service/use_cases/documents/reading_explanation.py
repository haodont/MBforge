"""Why one reading has no structure: the whole chain, in one read.

``query_activities`` says *that* a reading is unattributed and ``verify_structures``
says what the structures are, but the answer to "which link is broken" was spread
across five capabilities and the association source. Every diagnosis in the
patent-binding work re-derived that chain by hand, and two of them concluded the
wrong cause before the real one was measured. This module assembles the chain once,
read-only, so the next diagnosis starts from evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.service.use_cases.documents.activity_queries import (
    _document_context,
    _unattributed_reason,
    list_activity_records,
)
from mbforge.service.use_cases.documents.binding_candidates import binding_candidates

#: Read enough readings to hold one document's table; the same cap the candidate
#: package uses, so the two views cannot disagree about which reading exists.
_READING_LIMIT = 500


def explain_reading(
    library_root: str | Path, doc_id: str, measurement_id: str
) -> dict[str, Any]:
    """Return the six links between a printed reading and its structure.

    The sections are the ones a diagnosis needs, in pipeline order: what the
    document printed, which space the reference belongs to, what the drawings
    carry, what the entry side says, why the current rule stopped, and what to do
    next. Nothing here decides an attribution — the reason is the same derivation
    the dataset reports, quoted with its inputs.
    """
    rows = list_activity_records(library_root, doc_id, limit=_READING_LIMIT)
    reading = next(
        (row for row in rows if row.get("activity_id") == measurement_id), None
    )
    if reading is None:
        # The id may be the record id rather than the activity id.
        reading = next(
            (row for row in rows if row.get("measurement_id") == measurement_id), None
        )
    if reading is None:
        return {
            "doc_id": doc_id,
            "measurement_id": measurement_id,
            "found": False,
            "next_step": "no stored reading carries this id on this document",
        }

    key = str(reading.get("reference_key") or "").strip()
    reference_type = str(reading.get("reference_type") or "")
    context = _document_context(str(library_root), doc_id)
    reason = _unattributed_reason(
        key,
        context["drawn"],
        context["unlabeled"],
        context["detections"],
        context["grouped"],
    )

    packet = binding_candidates(library_root, doc_id, only_key=key, limit=1)
    designation: dict[str, Any] = next(iter(packet.get("designations") or []), {})

    return {
        "doc_id": doc_id,
        "measurement_id": measurement_id,
        "found": True,
        "printed": {
            "reference_raw": reading.get("reference_raw"),
            "reference_key": key,
            "reference_type": reference_type,
            "metric": reading.get("metric"),
            "value": reading.get("value"),
            "unit": reading.get("unit"),
            "page": reading.get("page_num"),
            "table_idx": reading.get("table_idx"),
            "row_idx": reading.get("row_idx"),
        },
        "reference_space": {
            # An example reference names the compound its section prepares, not the
            # compound with the same number — the two are different facts.
            "kind": reference_type or "unreadable",
            "key": key,
            "warning": (
                "an example reference binds through the section that prepares it"
                if reference_type == "example"
                else ""
            ),
        },
        "drawings": {
            "carrying_the_designation": designation.get("candidates") or [],
            "unlabelled_on_the_readings_pages": designation.get("nearby_structures")
            or [],
            "drawn_designation_count": len(context["drawn"]),
            "unlabelled_structure_count": context["unlabeled"],
            "detection_count": context["detections"],
        },
        "entry_side": [
            candidate.get("entry")
            for candidate in (designation.get("candidates") or [])
            if candidate.get("entry")
        ],
        "verdict": {
            "attributed": bool(reading.get("attributed")),
            "mol_ids": reading.get("mol_ids") or [],
            "reason": reason,
            # The reason and the review queue used to disagree about the same
            # reading; both now read the drawings, and this field says so.
            "reason_inputs": {
                "designation_in_drawn_set": key in context["drawn"],
                "designation_in_group_caption": key in context["grouped"],
                "unlabelled_structures": context["unlabeled"],
            },
        },
        "next_step": _next_step(reason, bool(reading.get("attributed"))),
    }


def _next_step(reason: str, attributed: bool) -> str:
    if attributed:
        return "nothing to repair: the reading has a structure"
    if reason == "designation_group_caption":
        return (
            "declared unsupported (docs/known-limitations.md): a caption names a set "
            "and choosing a member would be an invention"
        )
    if reason == "structure_detected_unmatched":
        return (
            "the drawing carries the designation: fix the entry/association side, "
            "no re-extraction needed"
        )
    if reason == "label_not_read":
        return (
            "the drawing exists without its number: check the caption geometry "
            "(head/foot bands, caption inside the box, caption row columns) before "
            "re-extracting"
        )
    if reason == "no_printed_designation":
        return "the cell names no compound: read the table header and the row"
    return "re-read the source page before changing a rule"

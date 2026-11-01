"""Project Patent artifact measurements into SQL reading rows.

The artifact already carries every reading the document printed, with its value,
comparator, unit, evidence IDs and the designation it cites. This module turns
that list into :class:`MeasurementRecord` rows — **without** requiring a
structure — and into :class:`MeasurementAttribution` rows for the readings whose
structure did resolve.

Keeping the two apart is the point: a reading no structure owns is still a fact
the document printed, and it must be storable, citable and countable.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from mbforge.contracts.measurement import (
    MeasurementAttribution,
    MeasurementRecord,
)
from mbforge.foundation.ids import stable_id
from mbforge.service.pipeline.activity.normalization import normalize_stored_measurement

#: Link statuses the domain uses (``mbforge.domain.activity``). ``linked`` there
#: means "this pass resolved its relation issues" — it does NOT mean a structure
#: was attached, so it is stored verbatim and never read as attribution.
_LINK_STATUSES = frozenset({"pending", "linked", "failed", "unlinked"})
_REVIEW_STATUSES = frozenset({"pending", "accepted", "rejected"})


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: Any) -> str | None:
    text = _text(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _assay_index(assay_methods: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for method in assay_methods:
        if not isinstance(method, Mapping):
            continue
        method_id = _text(method.get("assay_method_id"))
        if method_id:
            index[method_id] = method
    return index


def _assay_scope(method: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Read the target/assay columns a measurement row carries.

    The assay section supplies defaults; a table column can state its own target.
    Dataset queries use these copied fields without joining another table.
    """
    if method is None:
        return {
            "target": None,
            "species": None,
            "assay_type": None,
            "assay_description": None,
        }
    return {
        "target": _optional_text(method.get("target")),
        "species": _optional_text(method.get("system")),
        "assay_type": _optional_text(method.get("assay_type")),
        "assay_description": _optional_text(
            method.get("assay_description") or method.get("assay_type")
        ),
    }


def measurement_records(
    *,
    doc_id: str,
    run_id: str | None,
    measurements: Sequence[Mapping[str, Any]],
    assay_methods: Sequence[Mapping[str, Any]] = (),
) -> list[MeasurementRecord]:
    """Build one record per printed reading, regardless of structure.

    A reading is emitted whenever it has an id and something to cite. Readings
    without a resolvable structure are kept: that is the common case, and the
    reason this table exists.
    """
    assays = _assay_index(assay_methods)
    records: list[MeasurementRecord] = []
    seen: set[str] = set()
    for measurement in measurements:
        if not isinstance(measurement, Mapping):
            continue
        measurement_id = _text(measurement.get("measurement_id"))
        if not measurement_id or measurement_id in seen:
            continue
        value = measurement.get("value")
        value = value if isinstance(value, Mapping) else {}
        provenance = measurement.get("provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        assay_method_id = _optional_text(measurement.get("assay_method_id"))
        scope = _assay_scope(assays.get(assay_method_id) if assay_method_id else None)
        linking = _text(measurement.get("linking_status")) or "pending"
        if linking not in _LINK_STATUSES:
            linking = "pending"
        evidence_ids = [
            item
            for item in (measurement.get("evidence_ids") or [])
            if isinstance(item, str) and item
        ]
        entry_id = _optional_text(
            measurement.get("compound_entry_id") or measurement.get("entry_id")
        )
        metric = _optional_text(measurement.get("metric"))
        normalized = normalize_stored_measurement(metric, value)
        records.append(
            MeasurementRecord(
                measurement_id=measurement_id,
                doc_id=doc_id,
                entry_id=entry_id,
                assay_method_id=assay_method_id,
                metric=metric,
                activity_type=metric or "activity",
                measurement_kind=_text(
                    measurement.get("measurement_kind") or "quantitative"
                )
                or "quantitative",
                original_value=_float(value.get("original_value")),
                original_unit=_text(value.get("original_unit")),
                canonical_value=normalized.value_canonical,
                canonical_unit=normalized.unit_canonical or "",
                operator=normalized.operator,
                scale=normalized.scale,
                value_text=_optional_text(value.get("raw_text")),
                qualitative_raw=_text(value.get("qualitative_value")),
                qualitative_rank=(
                    value.get("qualitative_rank")
                    if isinstance(value.get("qualitative_rank"), int)
                    else None
                ),
                qualitative_scheme=_text(value.get("qualitative_scheme")),
                qualitative_label=_text(value.get("qualitative_label")),
                target=_optional_text(provenance.get("column_target"))
                or scope["target"],
                species=scope["species"],
                assay_type=scope["assay_type"],
                assay_description=scope["assay_description"],
                raw_text=_text(value.get("raw_text")),
                page_num=(
                    measurement.get("page_num")
                    if isinstance(measurement.get("page_num"), int)
                    else None
                ),
                table_idx=(
                    measurement.get("table_idx")
                    if isinstance(measurement.get("table_idx"), int)
                    else None
                ),
                row_idx=(
                    measurement.get("row_idx")
                    if isinstance(measurement.get("row_idx"), int)
                    else None
                ),
                col_idx=(
                    measurement.get("col_idx")
                    if isinstance(measurement.get("col_idx"), int)
                    else None
                ),
                row_label=_text(measurement.get("row_label")),
                reference_raw=_text(provenance.get("reference_raw")),
                reference_key=_text(provenance.get("reference_key")),
                reference_type=_text(provenance.get("reference_type")),
                evidence_ids=evidence_ids,
                provenance={
                    **provenance,
                    "operator_original": normalized.operator_original,
                },
                evidence_grade="measured",
                review_status="pending",
                linking_status=linking,
                run_id=run_id,
            )
        )
        seen.add(measurement_id)
    return records


def _owner_of(
    measurement: Mapping[str, Any],
    entries_by_id: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Resolve the structure a reading belongs to, whichever side carries it.

    A reading the model bound carries ``mol_id``; a reading whose designation
    resolved to a structure carries it on the cited entry. Both name the same
    molecule when they agree; conflicting references stay unattributed.
    """
    direct = _optional_text(measurement.get("mol_id"))
    entry_id = _optional_text(measurement.get("compound_entry_id"))
    if not entry_id:
        return direct
    entry = entries_by_id.get(entry_id)
    if entry is None:
        return direct
    indirect = _optional_text(entry.get("entity_id"))
    if direct and indirect and direct != indirect:
        return None
    return direct or indirect


def unattributed_reason(
    measurement: Mapping[str, Any],
    entries_by_id: Mapping[str, Mapping[str, Any]],
    *,
    document_has_detections: bool,
    unmatched_designations: Collection[str] = (),
) -> str | None:
    """Explain why a reading has no structure, or ``None`` when it has one.

    A single "unattributed" count cannot tell a medicinal chemist whether the
    document never drew the compound (a fact about the source) or whether a
    structure was detected and the rules could not bind it (a defect worth
    fixing). This is the pure classifier behind that split.

    ``unmatched_designations`` is the set of designations for which the document
    *did* print a structure that no rule managed to bind. A designation absent
    from both the entries' structures and that set was never drawn at all.
    """
    if _owner_of(measurement, entries_by_id):
        return None
    entry_id = _optional_text(measurement.get("compound_entry_id"))
    entry = entries_by_id.get(entry_id) if entry_id else None
    label_key = _text(entry.get("label_key")) if entry else ""
    if label_key and label_key in unmatched_designations:
        # A structure this document drew fits the designation, but no rule tied
        # them together. That is recoverable work, not a property of the source.
        return "structure_detected_unmatched"
    if not document_has_detections:
        return "document_has_no_detections"
    if not entry_id:
        return "no_printed_designation"
    # The designation is printed; the document simply never drew its structure.
    return "designation_without_structure"


def measurement_attributions(
    *,
    doc_id: str,
    records: Iterable[MeasurementRecord],
    measurements: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]] = (),
    method: str = "rule",
) -> list[MeasurementAttribution]:
    """Build the ``reading -> structure`` links that actually resolved.

    Readings with no owner produce no row — that is the extraction backlog, not
    an error. The stable id keeps a re-run idempotent.
    """
    by_id = {
        _text(entry.get("entry_id")): entry
        for entry in entries
        if isinstance(entry, Mapping) and _text(entry.get("entry_id"))
    }
    known = {record.measurement_id for record in records}
    attributions: list[MeasurementAttribution] = []
    seen: set[tuple[str, str]] = set()
    for measurement in measurements:
        if not isinstance(measurement, Mapping):
            continue
        measurement_id = _text(measurement.get("measurement_id"))
        if not measurement_id or measurement_id not in known:
            continue
        mol_id = _owner_of(measurement, by_id)
        if not mol_id:
            continue
        key = (measurement_id, mol_id)
        if key in seen:
            continue
        seen.add(key)
        evidence_ids = [
            item
            for item in (measurement.get("evidence_ids") or [])
            if isinstance(item, str) and item
        ]
        attributions.append(
            MeasurementAttribution(
                attribution_id=stable_id("attr", measurement_id, mol_id, method),
                measurement_id=measurement_id,
                mol_id=mol_id,
                doc_id=doc_id,
                method=method,  # type: ignore[arg-type]
                confidence=None,
                evidence_id=evidence_ids[0] if evidence_ids else None,
                review_status="pending",
            )
        )
    return attributions


__all__ = ["measurement_attributions", "measurement_records", "unattributed_reason"]

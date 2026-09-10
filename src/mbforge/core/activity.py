"""Activity domain objects: measurements, assay methods, measurement values.

An :class:`ActivityMeasurement` exists as first-class data even when the
measured compound has no recognized structure — ``compound_entry_id`` and
``mol_id`` are both optional and unlinked measurements are never dropped.

The Patent stage emits these document-local measurements before downstream linking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from mbforge.core.evidence import _stable_id

#: Linking lifecycle values (strings — round-trip through JSON).
LINK_PENDING = "pending"
LINK_LINKED = "linked"
LINK_FAILED = "failed"


def make_assay_method_id(doc_id: str, section_id: str) -> str:
    """Deterministic assay-method ID: doc + type + owning section."""
    return _stable_id("assay", doc_id, section_id)


def make_measurement_id(
    doc_id: str, page: int | None, metric: str, raw_value: str, row_label: str
) -> str:
    """Deterministic measurement ID from doc + evidence position + value.

    Includes the raw value text so two different numbers in the same
    cell/row never collide; re-runs reproduce the same ID (spec §3.5.3).
    """
    return _stable_id(
        "measurement", doc_id, str(page or ""), metric, raw_value, row_label
    )


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class MeasurementValue:
    """Original and canonical readings of one activity number.

    Decimal in the domain layer; JSON stores the raw string plus numeric
    fields — Decimal↔float conversion only happens at the file boundary
    (spec §5.3). ``raw_text`` keeps the printed form verbatim.
    """

    raw_text: str = ""
    operator: str = ""
    original_value: Decimal | None = None
    original_unit: str = ""
    canonical_value: Decimal | None = None
    canonical_unit: str = ""
    qualitative_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "operator": self.operator,
            "original_value": (
                float(self.original_value) if self.original_value is not None else None
            ),
            "original_unit": self.original_unit,
            "canonical_value": (
                float(self.canonical_value)
                if self.canonical_value is not None
                else None
            ),
            "canonical_unit": self.canonical_unit,
            "qualitative_value": self.qualitative_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeasurementValue:
        return cls(
            raw_text=data.get("raw_text", ""),
            operator=data.get("operator", ""),
            original_value=_to_decimal(data.get("original_value")),
            original_unit=data.get("original_unit", ""),
            canonical_value=_to_decimal(data.get("canonical_value")),
            canonical_unit=data.get("canonical_unit", ""),
            qualitative_value=data.get("qualitative_value", ""),
        )


@dataclass
class AssayMethod:
    """A bioassay described in the document (one per assay section).

    ``comparison_key`` stays ``None`` until a human confirms it or (M5)
    (target, system, endpoint, unit) match exactly — never auto-generated
    before then (spec §5.5).
    """

    assay_method_id: str
    doc_id: str
    target: str | None = None
    system: str | None = None
    endpoint: str | None = None
    assay_type: str | None = None
    conditions: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    section_id: str = ""
    page_start: int = 0
    page_end: int = 0
    comparison_key: str | None = None
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assay_method_id": self.assay_method_id,
            "doc_id": self.doc_id,
            "target": self.target,
            "system": self.system,
            "endpoint": self.endpoint,
            "assay_type": self.assay_type,
            "conditions": self.conditions,
            "raw_text": self.raw_text,
            "section_id": self.section_id,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "comparison_key": self.comparison_key,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssayMethod:
        return cls(
            assay_method_id=data["assay_method_id"],
            doc_id=data["doc_id"],
            target=data.get("target"),
            system=data.get("system"),
            endpoint=data.get("endpoint"),
            assay_type=data.get("assay_type"),
            conditions=data.get("conditions") or {},
            raw_text=data.get("raw_text", ""),
            section_id=data.get("section_id", ""),
            page_start=data.get("page_start", 0),
            page_end=data.get("page_end", 0),
            comparison_key=data.get("comparison_key"),
            evidence_ids=list(data["evidence_ids"]),
        )


@dataclass
class ActivityMeasurement:
    """One measured value tied to (optionally) an entry and an assay.

    ``compound_entry_id``/``assay_method_id``/``mol_id`` are all nullable:
    an unlinked measurement is valid data, never dropped (spec §3.4).
    """

    measurement_id: str
    doc_id: str
    value: MeasurementValue
    compound_entry_id: str | None = None
    assay_method_id: str | None = None
    mol_id: str | None = None
    metric: str | None = None
    linking_status: str = LINK_PENDING
    evidence_ids: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurement_id": self.measurement_id,
            "doc_id": self.doc_id,
            "compound_entry_id": self.compound_entry_id,
            "assay_method_id": self.assay_method_id,
            "mol_id": self.mol_id,
            "metric": self.metric,
            "linking_status": self.linking_status,
            "value": self.value.to_dict(),
            "evidence_ids": list(self.evidence_ids),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActivityMeasurement:
        return cls(
            measurement_id=data["measurement_id"],
            doc_id=data["doc_id"],
            value=MeasurementValue.from_dict(data.get("value") or {}),
            compound_entry_id=data.get("compound_entry_id"),
            assay_method_id=data.get("assay_method_id"),
            mol_id=data.get("mol_id"),
            metric=data.get("metric"),
            linking_status=data.get("linking_status", LINK_PENDING),
            evidence_ids=list(data["evidence_ids"]),
            provenance=data.get("provenance") or {},
        )

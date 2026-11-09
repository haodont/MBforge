"""Activity reading contracts: a printed reading and its structure attribution.

A patent prints ``化合物 77-A, CYP3A4 IC50 = 12 nM, page 152, table 3``. That
reading is complete and citable whether or not the document's drawn structure
for ``77-A`` was recognized, so it is modelled as its own row — never as a
column on a molecule. The link from a reading to a structure is a separate,
optional row, filled in as the association improves.

``evidence_grade`` is the other half of the contract: a figure the document
printed is not interchangeable with one a model produced. Phase A emits only
``measured``; compute paths must supply their own grade rather than reuse this
one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Where a reading's number came from. ``measured`` is a figure the source
#: document printed; the rest are model outputs and must never be presented as
#: observed data.
EvidenceGrade = Literal["measured", "predicted", "derived", "suggested"]

#: Review kind for a printed reading whose structure the rules could not bind
#: while the document does draw candidate structures on that page. A human
#: picks one on confirm, which writes the attribution (method=human).
DESIGNATION_UNBOUND_KIND = "designation_unbound"

#: Review lifecycle of a reading or an attribution.
ReviewStatus = Literal["pending", "accepted", "rejected"]

#: How an attribution was produced.
AttributionMethod = Literal["rule", "model", "human"]

#: Linking lifecycle carried over from the Patent stage
#: (``mbforge.domain.activity`` LINK_*). ``linked`` records that this pass
#: resolved its relation issues — it does NOT mean a structure was attached;
#: read ``measurement_attribution`` for that.
LinkingStatus = Literal["pending", "linked", "failed", "unlinked"]


class MeasurementRecord(BaseModel):
    """One printed activity reading, independent of any structure.

    ``entry_id`` names the designation the passage printed (``77-A``, an
    example number); it is the owner a human would use before any structure is
    known. ``evidence_ids`` are the ``source_evidence`` rows the reading was
    read from, so every number stays traceable to a page.
    """

    model_config = ConfigDict(extra="forbid")

    measurement_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    entry_id: str | None = None
    assay_method_id: str | None = None
    metric: str | None = None
    activity_type: str = "activity"
    measurement_kind: str = "quantitative"
    original_value: float | None = None
    original_unit: str = ""
    canonical_value: float | None = None
    canonical_unit: str = ""
    operator: str = ""
    scale: str = "linear"
    value_text: str | None = None
    qualitative_raw: str = ""
    qualitative_rank: int | None = None
    qualitative_scheme: str = ""
    qualitative_label: str = ""
    target: str | None = None
    species: str | None = None
    assay_type: str | None = None
    assay_description: str | None = None
    raw_text: str = ""
    page_num: int | None = None
    table_idx: int | None = None
    row_idx: int | None = None
    col_idx: int | None = None
    row_label: str = ""
    reference_raw: str = ""
    reference_key: str = ""
    reference_type: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: dict[str, object] = Field(default_factory=dict)
    evidence_grade: EvidenceGrade = "measured"
    review_status: ReviewStatus = "pending"
    linking_status: LinkingStatus = "pending"
    run_id: str | None = None


class MeasurementAttribution(BaseModel):
    """One ``reading -> structure`` link.

    A reading may carry several candidates (an unresolved conflict keeps both),
    and a reading may carry none at all. Neither is an error.
    """

    model_config = ConfigDict(extra="forbid")

    attribution_id: str = Field(min_length=1)
    measurement_id: str = Field(min_length=1)
    mol_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    method: AttributionMethod = "rule"
    confidence: float | None = None
    evidence_id: str | None = None
    review_status: ReviewStatus = "pending"


class MeasurementQuery(BaseModel):
    """Filters a dataset read. Empty strings mean "no filter"."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = ""
    target: str = ""
    assay_description: str = ""
    evidence_grade: str = ""
    review_status: str = ""
    metric: str = ""
    #: Canonical-value window: a dataset question such as "IC50 < 40 nM".
    min_value: float | None = None
    max_value: float | None = None
    limit: int = Field(200, ge=1, le=1000)


#: Why a reading has no structure.
#:
#: The distinction is the product value: "this document never drew the
#: compound" is information a medicinal chemist needs, while "we detected the
#: structure but could not bind the label" is a fixable defect. Reporting one
#: undifferentiated "unattributed" count hides which is which.
#:
#: - ``no_printed_designation`` — the reading names no compound at all.
#: - ``designation_without_structure`` — the document prints the designation but
#:   never draws its structure (SFC/LC-MS-only compounds: ``77-A``, ``77-B``).
#:   Not a defect: the source genuinely carries no structure to bind.
#: - ``label_not_read`` — structures were drawn but their printed designations
#:   were never read (or the read was ambiguous). Recoverable extraction work;
#:   counting it as ``designation_without_structure`` would understate the backlog.
#: - ``structure_detected_unmatched`` — a structure exists in the document but
#:   no rule could tie it to this designation. This is the real extraction gap.
#: - ``document_has_no_detections`` — the document yielded no structures at all,
#:   so nothing could have been attributed.
UnattributedReason = Literal[
    "no_printed_designation",
    "designation_without_structure",
    "label_not_read",
    "structure_detected_unmatched",
    "document_has_no_detections",
]


class MeasurementDatasetStats(BaseModel):
    """Counts that make coverage measurable instead of guessed.

    ``attributed`` is what SAR and compute work require; ``total`` is what the
    document actually printed. ``unattributed_by_reason`` splits the gap so a
    consumer can tell "the source has no structure" apart from "we failed to
    bind a structure we did detect".
    """

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    attributed: int = 0
    unattributed: int = 0
    pending_review: int = 0
    attached_to_a_designation: int = 0
    """Readings that name a printed designation, whether or not it has a structure."""
    unattributed_by_reason: dict[str, int] = Field(default_factory=dict)
    by_target: dict[str, int] = Field(default_factory=dict)
    by_assay: dict[str, int] = Field(default_factory=dict)


__all__ = [
    "DESIGNATION_UNBOUND_KIND",
    "AttributionMethod",
    "EvidenceGrade",
    "LinkingStatus",
    "MeasurementAttribution",
    "MeasurementDatasetStats",
    "MeasurementQuery",
    "MeasurementRecord",
    "ReviewStatus",
    "UnattributedReason",
]

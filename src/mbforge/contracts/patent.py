"""Patent-analysis contracts: LLM draft, conflicts, decisions, snapshots.

These models are the authoritative definitions of what the analysis sidecar
may submit (:class:`PatentDraft`) and of what Python validates, aligns,
reviews and publishes (conflicts, human decisions, the committed snapshot).
The Node sidecar consumes the exported, versioned JSON Schema
(``uv run python -m mbforge.contracts.schema_export``) instead of a
hand-maintained second copy of these fields.

V1 scope: the draft carries prose assay methods, activity measurements and
association suggestions only. Sections, entries, structures and labels stay
deterministic, the model never generates or edits SMILES, and final business
IDs are computed by Python.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mbforge.domain.activity import is_log_potency_metric

#: Draft protocol version understood by this module.
PROTOCOL_VERSION = "1"

#: Where a fact came from.
FactSource = Literal["deterministic", "llm", "agreed", "human"]

#: Whether a fact may be used downstream. ``accepted`` only means the adoption
#: rules were satisfied — never that the measurement is experimentally proven.
FactStatus = Literal["accepted", "pending_review", "rejected"]

#: Terminal outcome of one analysis attempt.
AnalysisStatus = Literal["disabled", "succeeded", "partial", "fallback"]

#: How the published facts were produced. A merged result that includes
#: deterministic facts is ``hybrid`` — never label it as pure LLM.
ExtractionMode = Literal["deterministic", "hybrid"]

#: Protocol version of the gap-answer path (v1 drafts stay readable).
GAP_PROTOCOL_VERSION = "2"

#: What kind of rule gap one answer addresses. The unit of work is one gap:
#: a refusal or omission whose boundary is small enough that one bounded
#: excerpt settles it. ``table`` = a refused activity table, ``prose_measurement``
#: = an unparsed or unattributed prose value, ``assay_attribution`` = a value
#: whose assay is unknown, ``assay_method`` = an assay block with no heading.
GapKind = Literal["table", "prose_measurement", "assay_attribution", "assay_method"]

#: ``needs_excerpt`` asks for exactly one bounded follow-up excerpt.
GapStatus = Literal["answered", "unanswerable", "needs_excerpt"]

#: Why a gap could not be answered. A closed enum, so giving up is countable
#: per form instead of hiding inside an empty item list.
UNANSWERABLE_REASONS = (
    "not_a_fact",
    "no_attribution",
    "glyph_damaged",
    "out_of_scope",
)
UnanswerableReason = Literal[
    "not_a_fact", "no_attribution", "glyph_damaged", "out_of_scope"
]

#: A reviewer's pick for one conflict slot; v1 has no free-text value edits.
DecisionChoice = Literal["deterministic", "llm", "neither"]

#: Review-queue kind for one contested Patent fact slot.
PATENT_FACT_REVIEW_KIND = "patent_fact_review"

#: Comparison operators allowed on a draft value, as printed in the source.
VALUE_OPERATORS = ("", "=", "<", "<=", ">", ">=", "~")

#: Fields a draft item may declare as missing; absence is recorded, never
#: guessed. A concentration without a printed unit declares ``unit`` missing;
#: dimensionless logarithmic potency metrics do not.
MISSING_FIELDS = (
    "value",
    "unit",
    "operator",
    "target",
    "system",
    "endpoint",
    "metric",
    "conditions",
)

_MAX_TEXT = 4000
_MAX_EVIDENCE_REFS = 50


class DraftValue(BaseModel):
    """One activity reading, preserving the source expression verbatim."""

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_TEXT,
        description="Verbatim source expression, e.g. '< 100 nM'.",
    )
    operator: str = Field(
        "=",
        max_length=8,
        description=(
            "Source comparison operator kept as printed. A bounded value must "
            "never be rewritten as exact ('< 100 nM' is not '100 nM')."
        ),
    )
    value: float | None = Field(
        None,
        allow_inf_nan=False,
        description="Printed number without the operator; null for qualitative readings.",
    )
    unit: str = Field(
        "",
        max_length=64,
        description="Unit as printed; empty for dimensionless pIC50/pEC50/pKi/pKd-style "
        "metrics (do not mark unit missing). Other numeric readings without a unit "
        "must declare unit in missing_fields. Canonicalization stays in Python.",
    )
    qualitative: str = Field(
        "", max_length=64, description="Qualitative label, e.g. '++' or 'inactive'."
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        max_length=len(MISSING_FIELDS),
        description="Fields the source does not state; recorded, never guessed.",
    )

    @model_validator(mode="after")
    def _reading_is_complete(self) -> DraftValue:
        if self.operator not in VALUE_OPERATORS:
            raise ValueError(f"unsupported operator: {self.operator!r}")
        if self.value is None and not self.qualitative:
            raise ValueError("a reading needs a number or a qualitative label")
        if len(set(self.missing_fields)) != len(self.missing_fields):
            raise ValueError("missing_fields contains duplicates")
        unknown = [name for name in self.missing_fields if name not in MISSING_FIELDS]
        if unknown:
            raise ValueError(f"unknown missing_fields entries: {unknown}")
        return self


class DraftAssayMethod(BaseModel):
    """A prose-described assay method the deterministic rules did not see."""

    model_config = ConfigDict(extra="forbid")

    local_key: str = Field(..., min_length=1, max_length=64)
    section_id: str | None = Field(None, max_length=64)
    target: str | None = Field(None, max_length=200)
    system: str | None = Field(
        None,
        max_length=200,
        description=(
            "Species/system as printed (e.g. human, mouse). Different systems "
            "never merge into one assay."
        ),
    )
    endpoint: str | None = Field(None, max_length=200)
    assay_type: str | None = Field(None, max_length=64)
    conditions: dict[str, str | float | int | bool | None] = Field(default_factory=dict)
    raw_text: str = Field("", max_length=_MAX_TEXT)
    page_start: int | None = Field(None, ge=1)
    page_end: int | None = Field(None, ge=1)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=_MAX_EVIDENCE_REFS)
    model_confidence: float | None = Field(
        None,
        ge=0,
        le=1,
        description=(
            "The model's own confidence, recorded for diagnostics only; "
            "never an adoption gate."
        ),
    )


class DraftMeasurement(BaseModel):
    """One activity record the rules missed, with its source anchors."""

    model_config = ConfigDict(extra="forbid")

    local_key: str = Field(..., min_length=1, max_length=64)
    metric: str = Field(..., min_length=1, max_length=64)
    value: DraftValue
    source_quote: str = Field(
        "",
        max_length=_MAX_TEXT,
        description="Verbatim row or sentence containing this designation and reading; "
        "required for table work with an evidence packet. Context/legend alone is not a reading.",
    )
    source_column: int | None = Field(
        None,
        ge=0,
        strict=True,
        description="Zero-based value column in the supplied Markdown work table (label columns count too); "
        "required for packet-backed pipe tables. raw_text must copy that cell exactly.",
    )
    compound_label_raw: str = Field("", max_length=200)
    row_label_raw: str = Field(
        "",
        max_length=200,
        description="The row designation exactly as printed: '实施例1', '1', "
        "'E020' or a chemistry name. The key alone loses which was printed, and "
        "the printed form decides what the designation means.",
    )
    compound_label_key: str = Field(
        "",
        max_length=64,
        description="Normalized compound reference; final IDs are Python's job.",
    )
    molecule_ref: str = Field(
        "",
        max_length=256,
        description="Existing candidate label key or mol_id this reading belongs "
        "to. Free-form SMILES is never accepted; empty means 'not recognized'.",
    )
    assay_local_key: str = Field(
        "",
        max_length=64,
        description="Local key of a draft assay method; empty when the assay "
        "context is inline on this record.",
    )
    target: str | None = Field(None, max_length=200)
    system: str | None = Field(None, max_length=200)
    endpoint: str | None = Field(None, max_length=200)
    conditions: dict[str, str | float | int | bool | None] = Field(default_factory=dict)
    page: int | None = Field(None, ge=1)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=_MAX_EVIDENCE_REFS)
    model_confidence: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _unit_matches_metric(self) -> DraftMeasurement:
        # Only the measurement knows whether an empty unit is missing or inapplicable.
        if is_log_potency_metric(self.metric):
            if self.value.unit.strip():
                raise ValueError(
                    "a logarithmic potency reading is dimensionless; unit must be empty"
                )
        elif (
            self.value.value is not None
            and not self.value.unit.strip()
            and "unit" not in self.value.missing_fields
        ):
            raise ValueError(
                "a numeric reading without a unit must declare 'unit' in missing_fields"
            )
        return self


class DraftCoverage(BaseModel):
    """Which parts of the document the draft actually examined."""

    model_config = ConfigDict(extra="forbid")

    pages_viewed: list[int] = Field(..., max_length=2000)
    pages_uncovered: list[int] = Field(..., max_length=2000)
    notes: str = Field("", max_length=_MAX_TEXT)


class PatentGap(BaseModel):
    """One bounded rule gap handed to the model, with its excerpt.

    A gap is how the rules say *where* they stopped: the issue code, the
    evidence it names, the pages, and the verbatim excerpt an answer is judged
    against. The model does not choose its own boundary except through one
    bounded ``needs_excerpt`` request.
    """

    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(..., min_length=1, max_length=128)
    gap_kind: GapKind
    code: str = Field(..., min_length=1, max_length=64)
    message: str = Field("", max_length=_MAX_TEXT)
    page_start: int | None = Field(None, ge=1)
    page_end: int | None = Field(None, ge=1)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=_MAX_EVIDENCE_REFS)
    excerpt: str = Field("", max_length=_MAX_TEXT)
    rule_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _page_range_is_ordered(self) -> PatentGap:
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end precedes page_start")
        return self


class PatentGapLink(BaseModel):
    """One association the rules could not make: a designation's owner.

    This is the model's *only* association output. It never states a reading, a
    value or a structure: it says which already-recognized structure the passage
    that prints ``label_raw`` belongs to, and cites the excerpt it read that from.
    The service accepts it only when the cited evidence lies inside the gap and the
    structure is one this document recognized.
    """

    model_config = ConfigDict(extra="forbid")

    label_raw: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="The designation exactly as the passage prints it ('化合物77').",
    )
    label_key: str = Field(
        "",
        max_length=64,
        description="Its normalized key when the printing is unambiguous ('77').",
    )
    mol_id: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="The mol_id of a structure this document recognized.",
    )
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_REFS)
    rationale: str = Field("", max_length=400)
    """Why this structure owns the designation, in the model's words."""


class PatentGapAnswer(BaseModel):
    """What the model returns for exactly one gap.

    The status decides what the rest may contain: an answered gap carries items
    or assay methods, an ``unanswerable`` gap carries a reason and no facts, and
    ``needs_excerpt`` asks for one bounded follow-up without asserting anything.
    """

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["2"] = "2"
    gap_id: str = Field(..., min_length=1, max_length=128)
    gap_kind: GapKind
    doc_id: str = Field(..., min_length=1, max_length=128)
    attempt_id: str = Field(..., min_length=1, max_length=128)
    evidence_signature: str = Field(..., min_length=1, max_length=128)
    status: GapStatus
    items: list[DraftMeasurement] = Field(default_factory=list, max_length=200)
    assay_methods: list[DraftAssayMethod] = Field(default_factory=list, max_length=50)
    links: list[PatentGapLink] = Field(default_factory=list, max_length=50)
    """Associations only: which recognized structure owns a printed designation."""
    unanswerable_reason: UnanswerableReason | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_REFS)
    model_confidence: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _status_matches_content(self) -> PatentGapAnswer:
        answered = bool(self.items or self.assay_methods or self.links)
        if self.status == "answered":
            if not answered:
                raise ValueError(
                    "an answered gap needs an item, an assay method or a link"
                )
            if self.unanswerable_reason is not None:
                raise ValueError("an answered gap carries no unanswerable_reason")
        elif self.status == "unanswerable":
            if answered:
                raise ValueError("an unanswerable gap carries no facts")
            if self.unanswerable_reason is None:
                raise ValueError("an unanswerable gap must name its reason")
        else:  # needs_excerpt
            if answered:
                raise ValueError("needs_excerpt asserts nothing")
            if self.unanswerable_reason is not None:
                raise ValueError("needs_excerpt is not a give-up")

        keys = [item.local_key for item in self.items] + [
            method.local_key for method in self.assay_methods
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate answer local keys")
        assay_keys = {method.local_key for method in self.assay_methods}
        for item in self.items:
            if item.assay_local_key and item.assay_local_key not in assay_keys:
                raise ValueError(
                    f"item {item.local_key!r} references unknown assay method "
                    f"{item.assay_local_key!r}"
                )
        return self


class PatentDraft(BaseModel):
    """The structured draft the sidecar submits for validation.

    Reference integrity inside the draft is part of the contract: local keys
    are unique, and every cross-reference resolves. Business IDs, evidence
    membership and adoption rules are validated later by the service layer.
    """

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1"] = "1"
    doc_id: str = Field(..., min_length=1, max_length=128)
    attempt_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Echoed from the run request; a stale attempt is rejected.",
    )
    evidence_signature: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Evidence set the draft was computed from; late drafts "
        "whose signature no longer matches are rejected.",
    )
    assay_methods: list[DraftAssayMethod] = Field(default_factory=list, max_length=200)
    measurements: list[DraftMeasurement] = Field(default_factory=list, max_length=2000)
    coverage: DraftCoverage

    @model_validator(mode="after")
    def _local_references_resolve(self) -> PatentDraft:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for key in [item.local_key for item in self.assay_methods] + [
            item.local_key for item in self.measurements
        ]:
            if key in seen:
                duplicates.add(key)
            seen.add(key)
        if duplicates:
            raise ValueError(f"duplicate draft local keys: {sorted(duplicates)}")

        assay_keys = {item.local_key for item in self.assay_methods}
        for measurement in self.measurements:
            if (
                measurement.assay_local_key
                and measurement.assay_local_key not in assay_keys
            ):
                raise ValueError(
                    f"measurement {measurement.local_key!r} references unknown "
                    f"assay method {measurement.assay_local_key!r}"
                )
        return self


class ConflictCandidate(BaseModel):
    """One side of a conflict: a value plus its content signature."""

    model_config = ConfigDict(extra="forbid")

    source: FactSource
    fields: dict[str, Any] = Field(
        ...,
        description="The compared field values; the signature covers exactly "
        "these fields.",
    )
    signature: str = Field(..., min_length=1, max_length=64)
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_REFS)


class PatentConflict(BaseModel):
    """One fact slot holding incompatible candidates.

    Both candidates are preserved and neither enters downstream results until
    a human decides. ``conflict_id`` doubles as the review item ID and is
    reused across re-runs while the slot and candidate set stay identical.
    """

    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(..., min_length=1, max_length=64)
    slot_id: str = Field(..., min_length=1, max_length=64)
    kind: Literal["measurement", "assay_method"]
    doc_id: str = Field(..., min_length=1, max_length=128)
    page: int | None = Field(None, ge=1)
    bbox: list[float] | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_REFS)
    candidates: list[ConflictCandidate] = Field(..., min_length=2, max_length=8)
    created_at: str | None = None

    @model_validator(mode="after")
    def _candidates_are_distinct(self) -> PatentConflict:
        signatures = [candidate.signature for candidate in self.candidates]
        if len(set(signatures)) != len(signatures):
            raise ValueError("conflict candidates must have distinct signatures")
        return self


class PatentDecision(BaseModel):
    """One human decision on a conflict slot (append-only; newest wins).

    The decision is reusable only while both signatures still match: a
    re-extract changes the evidence signature and a changed candidate set
    changes the candidate-set signature, either of which retires it.
    """

    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(..., min_length=1, max_length=64)
    choice: DecisionChoice
    candidate_set_signature: str = Field(..., min_length=1, max_length=64)
    evidence_signature: str = Field(..., min_length=1, max_length=128)
    reason: str = Field("", max_length=_MAX_TEXT)
    decided_at: str = Field(..., min_length=1, max_length=64)


class PatentAnalysisSnapshot(BaseModel):
    """The committed document-level analysis state (authoritative in SQL).

    ``patent_facts.json`` is a rebuildable projection of this row. The
    ``payload`` is validated by the service layer against the strict fact
    contract before commit; ``decisions`` maps slot IDs to the human
    decisions kept for reuse (stale entries are retained, not applied).
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(..., min_length=1, max_length=128)
    revision: int = Field(..., ge=1)
    evidence_signature: str = Field(..., min_length=1, max_length=128)
    analysis_status: AnalysisStatus
    extraction_mode: ExtractionMode
    payload: dict[str, Any]
    decisions: dict[str, PatentDecision] = Field(default_factory=dict)
    updated_at: str = Field(..., min_length=1, max_length=64)


__all__ = [
    "AnalysisStatus",
    "ConflictCandidate",
    "DecisionChoice",
    "DraftAssayMethod",
    "DraftCoverage",
    "DraftMeasurement",
    "DraftValue",
    "ExtractionMode",
    "FactSource",
    "FactStatus",
    "GAP_PROTOCOL_VERSION",
    "GapKind",
    "GapStatus",
    "MISSING_FIELDS",
    "PATENT_FACT_REVIEW_KIND",
    "PROTOCOL_VERSION",
    "PatentAnalysisSnapshot",
    "PatentConflict",
    "PatentDecision",
    "PatentDraft",
    "PatentGap",
    "PatentGapAnswer",
    "UNANSWERABLE_REASONS",
    "UnanswerableReason",
    "VALUE_OPERATORS",
]

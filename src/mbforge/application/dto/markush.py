"""Pydantic request/response models for the Markush review API.

These types are the public contract between the FastAPI router
(``mbforge.interfaces.http.markush``) and the frontend ``markush.ts`` HTTP
client. Adding a new field here is a wire-format change; coordinate it
with the matching TypeScript interface in ``frontend/src/types/index.ts``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# -- Recognition / review lifecycle ---------------------------------------

RecognizedRole = Literal["complete", "scaffold", "fragment", "review_required"]
ReviewStatus = Literal["pending", "confirmed", "rejected", "superseded"]
ReviewAction = Literal[
    "confirm_complete",
    "confirm_scaffold",
    "confirm_fragment",
    "reject",
    "reopen",
    "update",
]
RecognitionStatus = Literal["valid", "invalid", "low_quality"]
LabelKindName = Literal["formula", "r_group", "ring", "compound", "example", "unknown"]


# -- Read models -----------------------------------------------------------


class MarkushEvidenceItem(BaseModel):
    """One detection associated with a review entity."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: int
    entity_type: str
    entity_id: str
    doc_id: str
    page: int | None = None
    bbox_x0: float | None = None
    bbox_y0: float | None = None
    bbox_x1: float | None = None
    bbox_y1: float | None = None
    crop_relpath: str | None = None
    context_text: str | None = None
    moldet_confidence: float | None = None
    scribe_confidence: float | None = None
    composite_confidence: float | None = None


class MarkushDecisionItem(BaseModel):
    """A single audit entry from the decision log."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    action: str
    previous_state: str | None = None
    new_state: str | None = None
    reason: str = ""
    created_at: str | None = None


class MarkushCandidate(BaseModel):
    """One row in the review queue."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_key: str
    doc_id: str
    predicted_role: RecognizedRole
    smiles: str | None = None
    esmiles: str | None = None
    name: str = ""
    raw_label: str = ""
    normalized_label: str = ""
    label_kind: LabelKindName = "unknown"
    page: int | None = None
    bbox_x0: float | None = None
    bbox_y0: float | None = None
    bbox_x1: float | None = None
    bbox_y1: float | None = None
    crop_relpath: str | None = None
    moldet_confidence: float | None = None
    scribe_confidence: float | None = None
    composite_confidence: float | None = None
    reasons: list[str] = Field(default_factory=list)
    context_text: str = ""
    properties: dict[str, str] = Field(default_factory=dict)
    recognition_status: RecognitionStatus = "valid"
    review_status: ReviewStatus = "pending"
    review_version: int = 1
    superseded_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MarkushCandidateDetail(MarkushCandidate):
    """Candidate plus its full evidence chain and decision log."""

    scaffold_id: str | None = None
    fragment_id: str | None = None
    enumeration_eligible: bool = False
    enumeration_block_reasons: list[str] = Field(default_factory=list)
    evidence: list[MarkushEvidenceItem] = Field(default_factory=list)
    decisions: list[MarkushDecisionItem] = Field(default_factory=list)


# -- Write / request models ------------------------------------------------


class MarkushListRequest(BaseModel):
    """Filters for the queue listing endpoint."""

    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    doc_id: str | None = None
    review_status: ReviewStatus | None = None
    predicted_role: RecognizedRole | None = None
    reason: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class MarkushGetRequest(BaseModel):
    """Detail fetch by candidate_id."""

    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    candidate_id: str


class MarkushDecisionRequest(BaseModel):
    """Optimistic-lock-aware decision payload."""

    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    entity_id: str
    expected_version: int = Field(ge=1)
    action: ReviewAction
    reason: str = ""


class MarkushUpdateRequest(BaseModel):
    """Edit a candidate's structure / labels."""

    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    entity_id: str
    expected_version: int = Field(ge=1)
    smiles: str | None = None
    esmiles: str | None = None
    normalized_label: str | None = None
    raw_label: str | None = None
    predicted_role: RecognizedRole | None = None
    note: str = ""


# -- Response envelopes ----------------------------------------------------


class MarkushListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MarkushCandidate] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class MarkushDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    new_state: ReviewStatus
    new_version: int
    entity_id_after: str | None = None
    # ``molecule_id`` is non-null when ``action == 'confirm_complete'``;
    # ``scaffold_id`` / ``fragment_id`` for the corresponding transitions.
    molecule_id: str | None = None
    scaffold_id: str | None = None
    fragment_id: str | None = None

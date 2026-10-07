"""Markush read models shared with the persistence layer.

The ``db`` read path builds these from raw rows, so they live below ``service``
(the API DTO module re-exports them for its callers).
"""

from __future__ import annotations

from typing import Any, Literal

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
    source_evidence_id: str | None = None
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
    properties: dict[str, Any] = Field(default_factory=dict)
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


__all__ = [
    "LabelKindName",
    "MarkushCandidate",
    "MarkushCandidateDetail",
    "MarkushDecisionItem",
    "MarkushEvidenceItem",
    "RecognitionStatus",
    "RecognizedRole",
    "ReviewAction",
    "ReviewStatus",
]

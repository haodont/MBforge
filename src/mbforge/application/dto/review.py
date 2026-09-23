"""Pydantic models for the unified human-review queue.

Schemas for listing review items, submitting confirm/reject decisions,
and surfacing per-entity review history across detection, Markush, and
activity sources.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReviewKind = Literal[
    "low_conf_molecule",
    "review_required",
    "unparsable_smiles",
    "activity_match",
    "missing_evidence",
    "ambiguous_coref",
    "markush_link",
]
ReviewAction = Literal["confirm", "reject", "reopen"]


class ReviewQueueItem(BaseModel):
    id: str
    kind: str
    doc_id: str | None = None
    page: int | None = None
    bbox: list[float | None] | None = None
    crop_relpath: str | None = None
    smiles: str | None = None
    name: str | None = None
    confidence: float | None = None
    reasons: list[str] = Field(default_factory=list)
    context_text: str | None = None
    status: str = "pending"
    payload: dict = Field(default_factory=dict)
    created_at: str | None = None
    resolved_at: str | None = None


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class ReviewStatsItem(BaseModel):
    kind: str
    status: str
    count: int


class ReviewStatsResponse(BaseModel):
    items: list[ReviewStatsItem] = Field(default_factory=list)
    pending: int = 0


class ReviewDecisionItem(BaseModel):
    kind: str
    id: str
    # ambiguous_coref only: the reviewer-chosen compound identifier
    choice: str | None = None


class ReviewDecisionRequest(BaseModel):
    library_root: str | None = None
    items: list[ReviewDecisionItem] = Field(..., min_length=1, max_length=500)
    action: ReviewAction
    reason: str = ""


class ReviewDecisionResponse(BaseModel):
    updated: int = 0
    skipped: int = 0
    results: list[dict] = Field(default_factory=list)


class ReviewClearRequest(BaseModel):
    library_root: str | None = None


class ReviewClearResponse(BaseModel):
    deleted_items: int = 0
    deleted_candidates: int = 0


class ReviewHistoryResponse(BaseModel):
    entity_type: str
    entity_id: str
    history: list[dict] = Field(default_factory=list)

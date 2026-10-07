"""Pydantic request/response models for the Markush review API.

These types are the public contract between the FastAPI router
(``mbforge.api.http.markush``) and the frontend ``markush.ts`` HTTP
client. Adding a new field here is a wire-format change; coordinate it
with ``frontend/src/api/http/markush.ts``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Lifecycle literals and read models live in the neutral contracts layer (the
# ``db`` read path builds them); re-exported here for API/use-case callers.
from mbforge.contracts.markush import (  # noqa: F401
    LabelKindName,
    MarkushCandidate,
    MarkushCandidateDetail,
    MarkushDecisionItem,
    MarkushEvidenceItem,
    RecognitionStatus,
    RecognizedRole,
    ReviewAction,
    ReviewStatus,
)

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

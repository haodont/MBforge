"""AI review proposals: the agent may ask, a human decides.

The assistant works through the library and finds things the deterministic pass
got wrong or left undone. It is allowed to record that finding as a *proposal*
at any time: the proposal enters the review center with its evidence and a
before/after pair, and a human confirms or rejects it. A proposal never writes
a value itself, and once a human has decided the same target+field, the
assistant may not touch it again.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Review kind every proposal is stored under (``review_items.kind``).
AI_REVIEW_KIND = "ai_review"

#: What the proposal points at. Only existing rows / printed entries are allowed;
#: the model supplies an id, never a path or a new entity.
ProposalTargetKind = Literal[
    "evidence", "measurement", "molecule", "entry", "designation"
]

#: What happened to one proposal request.
ProposalAction = Literal["created", "updated", "unchanged", "refused"]


class ReviewProposal(BaseModel):
    """One proposed correction for one target field.

    ``before`` is what the model *claims* the current value is; the server
    records the actual value beside it (``before_actual``), so a hallucinated
    "before" is visible in the review item instead of being trusted.
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str | None = Field(default=None, max_length=128)
    target_kind: ProposalTargetKind
    target_id: str = Field(min_length=1, max_length=200)
    field: str = Field(default="", max_length=80)
    before: str = Field(default="", max_length=4000)
    after: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(default="", max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ReviewProposalResult(BaseModel):
    """Outcome of one proposal request."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = ""
    action: ProposalAction = "refused"
    status: str = ""
    error: str = ""
    #: The recorded proposal (``proposal`` + ``before_actual``) for a created or
    #: updated item; empty when refused.
    payload: dict[str, Any] = Field(default_factory=dict)

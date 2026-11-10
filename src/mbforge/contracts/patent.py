"""Patent-analysis contracts: conflicts, decisions, snapshots.

These models define the committed document-level analysis state: the facts
payload, contested slots, human decisions and the SQL-authoritative snapshot.
Sections, entries, structures and labels stay deterministic; no model draft is
part of this contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

#: A reviewer's pick for one conflict slot; v1 has no free-text value edits.
DecisionChoice = Literal["deterministic", "llm", "neither"]

#: Review-queue kind for one contested Patent fact slot.
PATENT_FACT_REVIEW_KIND = "patent_fact_review"

_MAX_TEXT = 4000
_MAX_EVIDENCE_REFS = 50


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
    "ExtractionMode",
    "FactSource",
    "FactStatus",
    "PATENT_FACT_REVIEW_KIND",
    "PatentAnalysisSnapshot",
    "PatentConflict",
    "PatentDecision",
]

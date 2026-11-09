"""Persisted research conversations and the private sidecar turn protocol."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ObjectId = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
]


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchTaskReference(ResearchModel):
    task_id: ObjectId
    run_id: ObjectId
    doc_id: ObjectId


class ResearchArtifactReference(ResearchModel):
    doc_id: ObjectId
    run_id: ObjectId
    revision: int = Field(ge=1)


class ResearchMoleculeReference(ResearchModel):
    mol_id: ObjectId
    name: str = Field(max_length=160)


class ResearchReviewReference(ResearchModel):
    """One AI proposal the assistant raised while answering.

    It travels with the reply so the browser can show an approve/reject card
    inline; approving calls the same review-decision endpoint the review
    center uses, and the proposal joins that queue either way.
    """

    item_id: ObjectId
    kind: str = Field(default="ai_review", max_length=40)
    doc_id: str = Field(default="", max_length=128)
    target_kind: str = Field(default="", max_length=40)
    target_id: str = Field(default="", max_length=200)
    field: str = Field(default="", max_length=80)
    before_actual: str = Field(default="", max_length=4000)
    after: str = Field(default="", max_length=4000)
    rationale: str = Field(default="", max_length=2000)
    status: str = Field(default="pending", max_length=20)


class ResearchContext(ResearchModel):
    document_ids: list[ObjectId] = Field(default_factory=list, max_length=8)
    molecule_refs: list[ResearchMoleculeReference] = Field(
        default_factory=list, max_length=8
    )
    task_refs: list[ResearchTaskReference] = Field(default_factory=list, max_length=8)
    allow_patent_analysis: bool = False


class ResearchMessage(ResearchModel):
    id: ObjectId
    request_id: ObjectId
    role: Literal["user", "assistant"]
    content: str = Field(max_length=60_000)
    status: Literal["pending", "complete", "stopped", "failed"] = "complete"
    context: ResearchContext | None = None
    task_refs: list[ResearchTaskReference] = Field(default_factory=list, max_length=24)
    artifact_refs: list[ResearchArtifactReference] = Field(
        default_factory=list, max_length=8
    )
    review_refs: list[ResearchReviewReference] = Field(
        default_factory=list, max_length=24
    )


class ResearchSession(ResearchModel):
    id: ObjectId
    title: str = Field(min_length=1, max_length=160)
    revision: int = Field(default=1, ge=1)
    updated_at: float = Field(ge=0)
    pi_context_used: bool = False
    context: ResearchContext = Field(default_factory=ResearchContext)
    messages: list[ResearchMessage] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_message_identities(self) -> ResearchSession:
        ids = [message.id for message in self.messages]
        turns = [(message.request_id, message.role) for message in self.messages]
        if len(ids) != len(set(ids)) or len(turns) != len(set(turns)):
            raise ValueError("message and turn-role identifiers must be unique")
        request_ids = {message.request_id for message in self.messages}
        if any(
            {
                message.role
                for message in self.messages
                if message.request_id == request_id
            }
            != {"user", "assistant"}
            for request_id in request_ids
        ):
            raise ValueError("each persisted turn requires a user message and a reply")
        if any(
            message.role == "user" and message.status != "complete"
            for message in self.messages
        ):
            raise ValueError("user messages must be complete")
        if sum(message.status == "pending" for message in self.messages) > 1:
            raise ValueError("a conversation may have only one running reply")
        if sum(len(message.content) for message in self.messages) > 4_000_000:
            raise ValueError("visible conversation exceeds its size limit")
        return self


class ResearchSessionSummary(ResearchModel):
    id: ObjectId
    title: str
    updated_at: float
    message_count: int


class ResearchTurnRequest(ResearchModel):
    request_id: ObjectId
    message: str = Field(min_length=1, max_length=20_000)
    context: ResearchContext = Field(default_factory=ResearchContext)


class ResearchTurnScope(ResearchModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    library_root: str
    session_id: ObjectId
    request_id: ObjectId
    context: ResearchContext
    message: str
    history: list[ResearchMessage]


class ResearchRuntimeSpec(ResearchModel):
    session_id: ObjectId
    session_file: str
    message: str
    context: ResearchContext
    history: list[ResearchMessage]


class ResearchDelta(ResearchModel):
    type: Literal["delta"] = "delta"
    text: str = Field(max_length=60_000)


class ResearchToolEvent(ResearchModel):
    type: Literal["tool"] = "tool"
    name: str = Field(max_length=80)
    status: Literal["start", "done", "error"]


class ResearchTaskEvent(ResearchModel):
    type: Literal["task"] = "task"
    reference: ResearchTaskReference


class ResearchArtifactEvent(ResearchModel):
    type: Literal["artifact"] = "artifact"
    reference: ResearchArtifactReference


class ResearchReviewEvent(ResearchModel):
    type: Literal["review"] = "review"
    items: list[ResearchReviewReference] = Field(default_factory=list, max_length=24)


class ResearchDone(ResearchModel):
    type: Literal["done"] = "done"
    text: str = Field(max_length=60_000)
    status: Literal["complete", "stopped", "failed"] = "complete"


class ResearchError(ResearchModel):
    type: Literal["error"] = "error"
    message: str = Field(max_length=500)


ResearchEvent = Annotated[
    ResearchDelta
    | ResearchToolEvent
    | ResearchTaskEvent
    | ResearchArtifactEvent
    | ResearchReviewEvent
    | ResearchDone
    | ResearchError,
    Field(discriminator="type"),
]

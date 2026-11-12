"""Read-only library briefing capability exposed to agents.

The briefing is the session's starting context: what the library holds, what is
running, what needs a human, and whether the worker can claim work. It is a
projection of the same stores the individual capabilities read, so it never
introduces a second source of truth. The agent's active goal is session state
and is deliberately absent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mbforge.service.capabilities.registry import (
    DOC_ID_DESCRIPTION,
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.use_cases.documents.briefing import library_briefing


class LibraryBriefingInput(BaseModel):
    """Library-wide by default; ``doc_id`` scopes runs, review and anchors."""

    doc_id: str = Field(
        "",
        max_length=128,
        description=f"{DOC_ID_DESCRIPTION} Empty means the whole library.",
    )


class DocumentOverview(BaseModel):
    total: int
    by_status: dict[str, int]


class BriefingRun(BaseModel):
    run_id: str
    doc_id: str | None = None
    short_id: str | None = None
    status: str
    stages: list[str] = Field(
        default_factory=list,
        description="Each stage as `stage=status`; call runs(action=get) for detail.",
    )


class WorkerOverview(BaseModel):
    status: str
    locked: bool
    active: int
    backlog: int
    model_gate: dict[str, Any] | None = None


class ReviewOverview(BaseModel):
    pending: int
    by_kind: dict[str, int] = Field(
        default_factory=dict, description="Pending item count per review kind."
    )


class AnchorOverview(BaseModel):
    anchors: int = 0
    documents: int = 0
    distinct_labels: int = 0
    by_key_space: dict[str, int] = Field(default_factory=dict)


class LibraryBriefingOutput(BaseModel):
    documents: DocumentOverview
    active_runs: list[BriefingRun] = Field(default_factory=list)
    worker: WorkerOverview
    review: ReviewOverview
    anchors: AnchorOverview


async def briefing(
    context: CapabilityContext, request: LibraryBriefingInput
) -> CapabilityResult:
    payload = await library_briefing(context.library_root, request.doc_id)
    return CapabilityResult(data=LibraryBriefingOutput(**payload))


register(
    Capability(
        name="library_briefing",
        description=(
            "One-call starting context for a session: document counts by status, "
            "active pipeline runs, queue/worker health (including the model "
            "gate), pending review items by kind, and printed-designation anchor "
            "coverage. Call it when a session starts or resumes, or when asked "
            "what is going on, instead of probing several tools. Read-only; it "
            "projects the same stores the other capabilities read and carries no "
            "session goal. Pass doc_id to scope runs, review and anchors to one "
            "document."
        ),
        input_model=LibraryBriefingInput,
        output_model=LibraryBriefingOutput,
        mutating=False,
        handler=briefing,
    )
)

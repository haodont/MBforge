"""Tool endpoints the Patent-analysis session calls back into.

Every request carries the short-lived credential issued for that attempt; the
bound scope (library, document, evidence signature) is resolved server-side, so
a model-supplied path, another document's id or a foreign evidence id is never
honoured. Requests are strictly typed; responses are tool payloads whose
envelope is ``{"success", "tool", "error"?}`` — a business failure the model can
correct is data, a transport failure stays a real HTTP error.

Tools:
    get-gap              one bounded gap, or the next unanswered one
    request-excerpt      the one bounded follow-up excerpt a gap may ask for
    list-molecules       existing recognized structures (never creates one)
    submit-gap-answer    validate one gap answer against its gap and stage it
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from mbforge.service.use_cases import patent_analysis as tools

router = APIRouter()


class TaskCredential(BaseModel):
    """Tool-call authorization: the attempt's short-lived credential."""

    credential: str = Field(..., min_length=8, max_length=128)


class GetGapRequest(TaskCredential):
    """Empty ``gap_id`` asks for the next unanswered gap."""

    gap_id: str = Field("", max_length=128)


@router.post("/tools/get-gap")
async def patent_get_gap(body: GetGapRequest) -> dict[str, Any]:
    """Return one bounded gap, or the next unanswered one."""

    return await asyncio.to_thread(tools.get_gap, body.credential, gap_id=body.gap_id)


class RequestExcerptRequest(TaskCredential):
    gap_id: str = Field(..., min_length=1, max_length=128)
    evidence_ids: list[str] = Field(
        default_factory=list, max_length=tools.MAX_EVIDENCE_IDS
    )
    page_from: int | None = Field(None, ge=1)
    page_to: int | None = Field(None, ge=1)


@router.post("/tools/request-excerpt")
async def patent_request_excerpt(body: RequestExcerptRequest) -> dict[str, Any]:
    """Fetch the one bounded follow-up excerpt a gap may ask for."""

    return await asyncio.to_thread(
        tools.request_excerpt,
        body.credential,
        gap_id=body.gap_id,
        evidence_ids=body.evidence_ids,
        page_from=body.page_from,
        page_to=body.page_to,
    )


class ListMoleculesRequest(TaskCredential):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=tools.MAX_PAGE_SIZE)
    label: str = Field(
        "",
        max_length=200,
        description=(
            "A printed designation to look up (化合物77, 77, 实施例7). Empty lists "
            "the whole catalogue; a label returns only the structures that carry it."
        ),
    )


@router.post("/tools/list-molecules")
async def patent_list_molecules(body: ListMoleculesRequest) -> dict[str, Any]:
    """List the bound document's recognized structures."""

    return await asyncio.to_thread(
        tools.list_molecules,
        body.credential,
        page=body.page,
        page_size=body.page_size,
        label=body.label,
    )


class SubmitGapAnswerRequest(TaskCredential):
    """The gap-answer contract is enforced by ``mbforge.contracts.patent``."""

    answer: dict[str, Any]


@router.post("/tools/submit-gap-answer")
async def patent_submit_gap_answer(
    body: SubmitGapAnswerRequest,
) -> dict[str, Any]:
    """Validate one gap answer against its gap and stage it."""

    return await asyncio.to_thread(
        tools.submit_gap_answer, body.credential, body.answer
    )


__all__ = ["router"]

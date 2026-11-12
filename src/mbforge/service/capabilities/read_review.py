"""Read-only review-queue capability exposed to agents.

The review queue is where a human decides what the pipeline would not: a
low-confidence structure, an ambiguous designation, a disputed patent-fact
reading. The queue rows live in SQL and already back the review center; this
module publishes the same rows, with the same kind/item_id identity the web
route ``/review?kind=&id=`` links to, so the agent can point a user at the
exact decision instead of describing it.
"""

from __future__ import annotations

import asyncio
from typing import Literal, get_args

from pydantic import BaseModel, Field

from mbforge.foundation.errors import ValidationError
from mbforge.service.capabilities.registry import (
    DOC_ID_DESCRIPTION,
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.dto.review import ReviewKind
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.review_queue import queue_page, stats_summary

#: Every kind the queue can hold. ``designation_unbound`` is in the DTO now;
#: deriving the set here keeps the rejection message and the store in step.
REVIEW_KINDS: frozenset[str] = frozenset(get_args(ReviewKind))


class ListReviewQueueInput(BaseModel):
    """One page of the unified review queue plus per-kind counts."""

    kind: str | None = Field(
        None,
        max_length=48,
        description=(
            "Review kind to list; omit for every kind. An unknown kind is "
            "rejected with the valid vocabulary instead of answering empty."
        ),
    )
    status: Literal["pending", "confirmed", "rejected"] | None = Field(
        "pending",
        description=(
            "Item status; defaults to pending, the items that still need a "
            "human. Pass null to list every status."
        ),
    )
    doc_id: str | None = Field(
        None,
        min_length=1,
        max_length=128,
        description=DOC_ID_DESCRIPTION,
    )
    offset: int = Field(0, ge=0, description="Number of matching items to skip.")
    limit: int = Field(25, ge=1, le=200, description="Maximum review items to return.")


class ReviewStatsRow(BaseModel):
    kind: str
    status: str
    count: int


class ReviewQueueEntry(BaseModel):
    """One queue row. ``item_id`` + ``kind`` address the review-center item."""

    item_id: str
    kind: str
    doc_id: str | None = None
    short_id: str | None = None
    page: int | None = None
    bbox: list[float | None] | None = None
    name: str | None = None
    smiles: str | None = None
    confidence: float | None = None
    status: str
    reasons: list[str] = Field(default_factory=list)
    created_at: str | None = None
    #: What the reviewer actually decides — the per-kind detail the review
    #: center renders (a reading's candidates, a proposal's before/after).
    payload: dict[str, object] = Field(default_factory=dict)


class ListReviewQueueOutput(BaseModel):
    items: list[ReviewQueueEntry] = Field(default_factory=list)
    total: int = 0
    pending: int = 0
    stats: list[ReviewStatsRow] = Field(default_factory=list)


def _queue_entry(item: dict[str, object]) -> ReviewQueueEntry:
    doc_id = item.get("doc_id")
    reasons = item.get("reasons")
    return ReviewQueueEntry(
        item_id=str(item["id"]),
        kind=str(item["kind"]),
        doc_id=str(doc_id) if doc_id else None,
        short_id=short_doc_id(str(doc_id)) if doc_id else None,
        page=item.get("page") if isinstance(item.get("page"), int) else None,
        bbox=item.get("bbox") if isinstance(item.get("bbox"), list) else None,
        name=str(item["name"]) if item.get("name") else None,
        smiles=str(item["smiles"]) if item.get("smiles") else None,
        confidence=(
            float(item["confidence"])
            if isinstance(item.get("confidence"), (int, float))
            else None
        ),
        status=str(item.get("status") or "pending"),
        reasons=[str(reason) for reason in reasons]
        if isinstance(reasons, list)
        else [],
        created_at=str(item["created_at"]) if item.get("created_at") else None,
        payload=(
            dict(item["payload"]) if isinstance(item.get("payload"), dict) else {}
        ),
    )


async def list_review_queue(
    context: CapabilityContext, request: ListReviewQueueInput
) -> CapabilityResult:
    if request.kind is not None and request.kind not in REVIEW_KINDS:
        raise ValidationError(
            "unknown review kind",
            detail=request.kind,
            context={"valid_kinds": sorted(REVIEW_KINDS)},
        )
    # The store pages by (page, page_size); an offset capability call maps onto
    # that page and skips the rows before ``offset``.
    page = request.offset // request.limit + 1
    skip = request.offset % request.limit
    queue = await asyncio.to_thread(
        queue_page,
        context.library_root,
        request.kind,
        request.status,
        request.doc_id,
        page,
        request.limit,
    )
    stats = await asyncio.to_thread(stats_summary, context.library_root, request.doc_id)
    rows = queue.items[skip:]
    next_offset = (
        request.offset + len(rows) if request.offset + len(rows) < queue.total else None
    )
    return CapabilityResult(
        data=ListReviewQueueOutput(
            items=[_queue_entry(item.model_dump()) for item in rows],
            total=queue.total,
            pending=int(stats.get("pending") or 0),
            stats=[ReviewStatsRow(**row) for row in stats.get("items") or []],
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


register(
    Capability(
        name="list_review_queue",
        description=(
            "The unified human-review queue: items the pipeline would not "
            "decide on its own (low-confidence or unparsable structures, "
            "ambiguous designations, disputed patent facts, AI proposals). "
            "Returns pending items by default with their kind, "
            "item_id, document/short_id, page, bbox, name, SMILES and "
            "confidence, plus per-kind counts. Each row is the same item the "
            "review center shows: kind + item_id address it in the web route "
            "/review?kind=&id=, and ``payload`` carries what the reviewer "
            "actually decides. Read-only; a decision needs the human in the "
            "review center, never a capability call."
        ),
        input_model=ListReviewQueueInput,
        output_model=ListReviewQueueOutput,
        mutating=False,
        handler=list_review_queue,
    )
)

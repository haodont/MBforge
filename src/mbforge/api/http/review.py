"""Unified review center endpoints.

Provides a single paginated queue and decision API for pending candidates
across Markush review, molecule corrections, and other reviewable entities.
Each decision is persisted with versioned optimistic-lock semantics. All
queue operations delegate to :mod:`mbforge.service.use_cases.review_queue`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from mbforge.api.http._path_utils import resolve_library_root
from mbforge.foundation.errors import NotFoundError
from mbforge.service.dto.review import (
    ReviewAssistRequest,
    ReviewAssistResponse,
    ReviewAssistResult,
    ReviewClearRequest,
    ReviewClearResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewFilterDecisionRequest,
    ReviewHistoryResponse,
    ReviewProposeRequest,
    ReviewProposeResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
    ReviewStatsResponse,
)
from mbforge.service.use_cases import review_assist, review_proposals
from mbforge.service.use_cases.review_queue import (
    clear_all_review_queue,
    decide_filtered,
    decide_items,
    entity_history,
    item_detail,
    queue_page,
    stats_summary,
)

router = APIRouter()


@router.get("/queue", response_model=ReviewQueueResponse)
async def review_queue(
    library_root: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    item_status: str | None = Query(default=None, alias="status"),
    doc_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ReviewQueueResponse:
    return await asyncio.to_thread(
        queue_page,
        library_root,
        kind,
        item_status,
        doc_id,
        page,
        page_size,
    )


@router.get("/stats", response_model=ReviewStatsResponse)
async def review_stats(
    library_root: str | None = Query(default=None),
) -> ReviewStatsResponse:
    summary = await asyncio.to_thread(stats_summary, library_root)
    return ReviewStatsResponse(**summary)


@router.get("/items/{kind}/{item_id}", response_model=ReviewQueueItem)
async def review_item(
    kind: str, item_id: str, library_root: str | None = Query(default=None)
) -> ReviewQueueItem:
    item = await asyncio.to_thread(item_detail, library_root, kind, item_id)
    return ReviewQueueItem(**item)


@router.post("/decide", response_model=ReviewDecisionResponse)
async def review_decide(body: ReviewDecisionRequest) -> ReviewDecisionResponse:
    return await asyncio.to_thread(
        decide_items, body.library_root, body.action, body.reason, body.items
    )


@router.post("/decide-filtered", response_model=ReviewDecisionResponse)
async def review_decide_filtered(
    body: ReviewFilterDecisionRequest,
) -> ReviewDecisionResponse:
    """Decide every pending item matching a server-side filter.

    ``target_kind=evidence`` approves all text-level proposals; ``doc_id``
    scopes the batch to one patent. Each item still goes through its own
    decision handler, so a kind-specific side effect is not skipped.
    """
    return await asyncio.to_thread(
        decide_filtered,
        str(resolve_library_root(body.library_root)),
        kind=body.kind,
        doc_id=body.doc_id,
        target_kind=body.target_kind,
        action=body.action,
        reason=body.reason,
        limit=body.limit,
    )


@router.post("/clear", response_model=ReviewClearResponse)
async def review_clear(body: ReviewClearRequest) -> ReviewClearResponse:
    """Empty the entire review center (queue rows + their audit trail)."""
    result = await asyncio.to_thread(clear_all_review_queue, body.library_root)
    return ReviewClearResponse(**result)


@router.post("/assist", response_model=ReviewAssistResponse)
async def review_assist_items(body: ReviewAssistRequest) -> ReviewAssistResponse:
    """Ask the model about review items; the answer is a stored suggestion.

    Bounded by ``review.max_items`` per call. An empty ``items`` list pulls the
    oldest pending items that have no suggestion yet, which is what the
    automatic pull uses.
    """
    root = str(resolve_library_root(body.library_root))
    targets = [{"kind": item.kind, "item_id": item.id} for item in body.items]
    results = await asyncio.to_thread(
        review_assist.assist_items,
        root,
        targets,
        limit=body.limit,
        force=body.force,
    )
    return ReviewAssistResponse(
        items=[ReviewAssistResult(**result) for result in results]
    )


@router.post("/propose", response_model=ReviewProposeResponse)
async def review_propose(body: ReviewProposeRequest) -> ReviewProposeResponse:
    """Record AI proposals for unreviewed evidence.

    The proposal enters the review center as ``ai_review``; it writes no value
    itself, and a target a human already decided is refused instead of
    overwritten.
    """
    root = str(resolve_library_root(body.library_root))
    results = await asyncio.to_thread(review_proposals.propose_items, root, body.items)
    return ReviewProposeResponse(items=results)


@router.get("/assist/{kind}/{item_id}", response_model=ReviewAssistResult)
async def review_assist_one(
    kind: str, item_id: str, library_root: str | None = Query(default=None)
) -> ReviewAssistResult:
    """Read the stored suggestion for one item (404 when none was requested)."""
    root = str(resolve_library_root(library_root))
    stored = await asyncio.to_thread(review_assist.assist_for, root, kind, item_id)
    if stored is None:
        raise NotFoundError("no AI suggestion for this item yet")
    return ReviewAssistResult(**stored)


@router.get("/history", response_model=ReviewHistoryResponse)
async def review_history(
    entity_id: str = Query(...),
    library_root: str | None = Query(default=None),
) -> ReviewHistoryResponse:
    entity_type, items = await asyncio.to_thread(
        entity_history, library_root, entity_id
    )
    return ReviewHistoryResponse(
        entity_type=entity_type, entity_id=entity_id, history=items
    )

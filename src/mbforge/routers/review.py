"""Unified review center endpoints.

Provides a single paginated queue and decision API for pending candidates
across Markush review, molecule corrections, and other reviewable entities.
Each decision is persisted with versioned optimistic-lock semantics. All
queue operations delegate to :mod:`mbforge.services.review_queue`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from ..models.review import (
    ReviewClearRequest,
    ReviewClearResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewHistoryResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
    ReviewStatsResponse,
)
from ..services.review_queue import (
    clear_all_review_queue,
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


@router.post("/clear", response_model=ReviewClearResponse)
async def review_clear(body: ReviewClearRequest) -> ReviewClearResponse:
    """Empty the entire review center (queue rows + their audit trail)."""
    result = await asyncio.to_thread(clear_all_review_queue, body.library_root)
    return ReviewClearResponse(**result)


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

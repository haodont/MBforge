"""Server-sent events (SSE) stream endpoints.

Pushes real-time model-loading status updates to connected frontend clients.
The stream is long-lived and sends a heartbeat every few seconds so the
connection stays open through intermediate proxies.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ...infra.models import get_all as get_model_statuses

router = APIRouter()


@router.get("/stream")
async def event_stream(request: Request) -> EventSourceResponse:
    """Global SSE event stream for all real-time updates."""

    async def generate():
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(5)
            statuses = get_model_statuses()
            yield {
                "event": "model_loading",
                "data": json.dumps({"models": statuses}),
            }

    return EventSourceResponse(generate())

"""Document processing pipeline endpoints.

Enqueue, monitor, and control asynchronous pipeline tasks that ingest PDFs
through OCR, molecule detection, Markdown generation, and Patent facts.
Queue semantics (worker status, SSE streaming, batch actions) live in
:mod:`mbforge.application.use_cases.pipeline.ingest`; these endpoints only validate
requests and shape HTTP responses.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from mbforge.application.dto.pipeline import (
    PipelineEnqueueRequest,
    PipelineEnqueueResponse,
    PipelineProcessRequest,
    PipelineProcessResponse,
    PipelineQueueRequest,
    PipelineQueueResponse,
    PipelineQueueStatsResponse,
    PipelineTaskActionResponse,
    PipelineTaskBatchRequest,
)
from mbforge.application.use_cases.pipeline import ingest
from mbforge.foundation.errors import ValidationError
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger
from mbforge.interfaces.http._path_utils import resolve_library_root

logger = get_logger("mbforge.application.pipeline_router")

router = APIRouter()


class PipelineLogsRequest(BaseModel):
    """Request body for fetching recent ingest logs of a document."""

    library_root: str | None = Field(
        default=None,
        description="Library root path. Falls back to global config when omitted.",
    )
    doc_id: str = Field(default="", description="Document identifier.")
    limit: int = Field(
        default=200, ge=1, le=1000, description="Max log rows to return."
    )


@router.post("/enqueue")
async def pipeline_enqueue(body: PipelineEnqueueRequest) -> PipelineEnqueueResponse:
    root = resolve_library_root(body.library_root)
    root_str = str(root)

    if body.action == "enqueue_unresolved":
        enqueued = await ingest.enqueue_all_unresolved(root_str)
        return PipelineEnqueueResponse(enqueued=enqueued)

    doc_id = body.doc_id or ""
    run_id = await ingest.enqueue(root_str, doc_id)
    return PipelineEnqueueResponse(run_id=run_id)


@router.post("/process")
async def pipeline_process(body: PipelineProcessRequest) -> PipelineProcessResponse:
    """Synchronous pipeline execution (blocks until complete)."""
    root = resolve_library_root(body.library_root)
    root_str = str(root)
    file_path = body.file_path
    doc_id = body.doc_id or ""
    if not file_path:
        raise ValidationError("file_path is required")
    task_id = short_id()
    from mbforge.application.pipeline.runner import run_pipeline

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: run_pipeline(file_path, root_str, doc_id=doc_id, run_id=task_id),
    )
    return PipelineProcessResponse(
        run_id=task_id,
        doc_id=result.doc_id,
        page_count=result.page_count,
        parser=result.parser,
        title=result.title,
        duration_ms=result.duration_ms,
    )


@router.post("/queue")
async def pipeline_queue(body: PipelineQueueRequest) -> PipelineQueueResponse:
    root = resolve_library_root(body.library_root)
    try:
        tasks = await ingest.list_tasks(str(root))
        return PipelineQueueResponse(tasks=tasks)
    except Exception as e:
        logger.warning("Failed to fetch queue: %s", e)
        return PipelineQueueResponse()


@router.get("/worker/status")
async def worker_status(
    library_root: str = Query("", description="Library root path"),
) -> dict:
    """Return the library queue worker's real status (see services facade)."""
    return await ingest.worker_status_payload(library_root or None)


@router.post("/queue/stats")
async def pipeline_queue_stats(
    body: PipelineQueueRequest,
) -> PipelineQueueStatsResponse:
    root = resolve_library_root(body.library_root)
    try:
        stats = await asyncio.to_thread(ingest.queue_snapshot, str(root))
        return PipelineQueueStatsResponse(stats=stats)
    except Exception as e:
        logger.warning("Failed to fetch queue stats: %s", e)
        return PipelineQueueStatsResponse()


@router.get("/events/{run_id}")
async def pipeline_events(
    run_id: str,
    request: Request,
    library_root: str = Query(..., description="Library root path"),
) -> EventSourceResponse:
    """Server-sent events stream for a single pipeline run."""
    root = resolve_library_root(library_root)
    return EventSourceResponse(
        ingest.stream_run_events(
            str(root), run_id, is_disconnected=request.is_disconnected
        )
    )


@router.post("/queue/batch/cancel")
async def pipeline_cancel_batch(
    body: PipelineTaskBatchRequest,
) -> PipelineTaskActionResponse:
    root = resolve_library_root(body.library_root)
    result = await ingest.cancel_batch(str(root), body.run_ids)
    return PipelineTaskActionResponse(
        updated=result.updated,
        skipped=result.skipped,
    )


@router.post("/queue/batch/retry")
async def pipeline_retry_batch(
    body: PipelineTaskBatchRequest,
) -> PipelineTaskActionResponse:
    root = resolve_library_root(body.library_root)
    result = await ingest.retry_batch(
        str(root), body.run_ids, resume_from_stage=body.resume_from_stage
    )
    return PipelineTaskActionResponse(
        updated=result.updated,
        skipped=result.skipped,
        error=result.error,
    )


@router.post("/queue/{run_id}/cancel")
async def pipeline_cancel(
    run_id: str,
    body: PipelineQueueRequest,
) -> PipelineTaskActionResponse:
    result = await pipeline_cancel_batch(
        PipelineTaskBatchRequest(library_root=body.library_root or "", run_ids=[run_id])
    )
    return result


@router.post("/queue/{run_id}/retry")
async def pipeline_retry(
    run_id: str,
    body: PipelineTaskBatchRequest,
) -> PipelineTaskActionResponse:
    result = await pipeline_retry_batch(
        PipelineTaskBatchRequest(
            library_root=body.library_root or "",
            run_ids=[run_id],
            resume_from_stage=body.resume_from_stage,
        )
    )
    return result


@router.post("/queue/{run_id}/delete")
async def pipeline_delete_task(
    run_id: str,
    body: PipelineQueueRequest,
) -> PipelineTaskActionResponse:
    root = resolve_library_root(body.library_root)
    deleted = await ingest.delete_task(str(root), run_id)
    return PipelineTaskActionResponse(updated=deleted)


@router.post("/queue/{run_id}/priority")
async def pipeline_set_priority(
    run_id: str,
    body: PipelineQueueRequest,
) -> PipelineTaskActionResponse:
    """Set task priority stub."""
    return PipelineTaskActionResponse()


@router.post("/queue/cleanup")
async def pipeline_cleanup(body: PipelineQueueRequest) -> PipelineTaskActionResponse:
    root = resolve_library_root(body.library_root)
    cleaned = await ingest.cleanup_done(str(root))
    return PipelineTaskActionResponse(cleaned=cleaned, updated=cleaned)


@router.post("/queue/logs")
async def pipeline_logs(body: PipelineLogsRequest) -> PipelineTaskActionResponse:
    """Return recent ingest log rows for a document.

    The frontend queue page calls this when the user expands the log panel
    for a task. The pipeline runner writes one row per emitted event into
    ``ingest_logs``; the matching rows are returned in chronological order.
    """
    root = resolve_library_root(body.library_root)
    if not body.doc_id:
        return PipelineTaskActionResponse(logs=[])

    try:
        logs = await ingest.fetch_doc_logs(str(root), body.doc_id, body.limit)
        return PipelineTaskActionResponse(logs=logs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch ingest logs for %s: %s", body.doc_id, exc)
        return PipelineTaskActionResponse(logs=[])

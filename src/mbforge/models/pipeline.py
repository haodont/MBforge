"""Pydantic models for the pipeline ingestion endpoints.

Schemas for enqueuing and synchronously processing PDFs, querying the
ingest queue, and controlling task lifecycle actions.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PipelineEnqueueRequest(BaseModel):
    """Request body for enqueueing a pipeline run."""

    library_root: str | None = Field(
        default=None,
        description="Library root path. Falls back to global config when omitted.",
    )
    action: str | None = Field(
        default=None,
        description="Special action, e.g. 'enqueue_unresolved'.",
    )
    doc_id: str = Field(default="", description="Document identifier to enqueue.")


class PipelineEnqueueResponse(BaseModel):
    """Response body for enqueueing a pipeline run."""

    success: bool = True
    task_id: str | None = Field(default=None, description="Assigned task ID.")
    enqueued: int | None = Field(
        default=None,
        description="Number of files enqueued for 'enqueue_unresolved' action.",
    )
    error: str | None = Field(default=None, description="Error message on failure.")


class PipelineProcessRequest(BaseModel):
    """Request body for synchronous pipeline processing."""

    library_root: str | None = Field(
        default=None,
        description="Library root path. Falls back to global config when omitted.",
    )
    file_path: str = Field(..., description="Path to the PDF to process.")
    doc_id: str = Field(default="", description="Optional document identifier.")


class PipelineProcessResponse(BaseModel):
    """Response body for synchronous pipeline processing."""

    success: bool = True
    task_id: str
    doc_id: str
    page_count: int
    parser: str
    title: str
    duration_ms: int
    error: str | None = None


class PipelineQueueRequest(BaseModel):
    """Request body for fetching the ingest queue."""

    library_root: str | None = Field(
        default=None,
        description="Library root path. Falls back to global config when omitted.",
    )


class PipelineTaskBatchRequest(BaseModel):
    """Request body for applying one action to a set of queue tasks."""

    library_root: str = Field(..., description="Library root path")
    task_ids: list[str] = Field(..., min_length=1, max_length=1000)
    resume_from_stage: str | None = Field(
        default=None,
        description="Optional stage to resume from (extract/detection/markdown/patent). "
        "If provided, the pipeline will restart from this stage; otherwise it resumes "
        "from the last completed stage checkpoint.",
    )


class PipelineQueueResponse(BaseModel):
    """Response body for fetching the ingest queue."""

    success: bool = True
    tasks: list[dict] = Field(default_factory=list)


class PipelineQueueStatsResponse(BaseModel):
    """Response body for queue statistics."""

    success: bool = True
    stats: dict = Field(default_factory=dict)


class PipelineTaskActionResponse(BaseModel):
    """Generic response for task actions (cancel, retry, delete, etc.)."""

    success: bool = True
    cleaned: int | None = None
    updated: int = 0
    skipped: int = 0
    logs: list[dict] | None = None
    error: str | None = None

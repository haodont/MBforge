"""Diagnostics router — surface error ring buffer + ingest client-side errors.

Three read endpoints query the in-process ring buffer (see utils/logger.py).
The write endpoint accepts batches of client-side errors thrown into the
front-end ErrorBoundary, mirrored back into the same buffer so operators get
a unified view from `/api/v1/diagnostics/errors`. An export endpoint snapshots
the ring buffer to a JSON file so diagnostics survive process restarts.

Why a single process-wide ring buffer: errors need to be inspectable while
the system is still running. Persisting to SQLite would force a migration to
inspect, defeating the "users-look-at-it-when-stuck" use case. For durable
sinks, export the buffer on demand (POST /export) or enable JSON file
logging (setup_logging(json_mode=True)).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...utils.logger import (
    get_diagnostic_by_id,
    get_diagnostic_stats,
    get_diagnostics,
    get_logger,
    push_diagnostic,
)

logger = get_logger(__name__)

router = APIRouter()


class ClientErrorItem(BaseModel):
    message: str
    name: str | None = None
    stack: str | None = None
    category: str | None = "client"
    severity: str | None = "ERROR"
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: float | None = None


class ClientErrorBatch(BaseModel):
    errors: list[ClientErrorItem] = Field(default_factory=list)


@router.get("/errors")
async def list_errors(
    since: int | None = Query(default=None, ge=0),
    level: str | None = Query(default=None),
    category: str | None = Query(default=None),
    error_code: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """List recent diagnostic records, optionally filtered."""
    records = get_diagnostics(
        since=since,
        level=level,
        category=category,
        error_code=error_code,
        limit=limit,
    )
    return {"count": len(records), "errors": records}


@router.get("/errors/{seq_id}")
async def get_error(seq_id: int) -> dict[str, Any]:
    """Look up a single diagnostic record by seq, or 404."""
    rec = get_diagnostic_by_id(seq_id)
    if rec is None:
        return {"success": False, "error": "not found", "seq": seq_id}
    return rec


@router.get("/stats")
async def stats() -> dict[str, Any]:
    """Aggregate counts — by level, category, error_code, total."""
    return get_diagnostic_stats()


@router.get("/tasks")
async def task_stats() -> dict[str, Any]:
    """Live capacity / running / queued for each managed background pool."""
    from ...infra.process import tasks

    return {
        "pools": {
            str(pool): {
                "capacity": stat.capacity,
                "running": stat.running,
                "queued": stat.queued,
            }
            for pool, stat in tasks.stats().items()
        }
    }


@router.post("/errors", status_code=status.HTTP_204_NO_CONTENT)
async def report_client_error(batch: ClientErrorBatch) -> None:
    """Ingest a batch of front-end caught errors.

    Each item is pushed into the same ring buffer used by the backend
    exception handler, tagged with `category: client`. Returns 204 with no
    body — clients should treat the call as fire-and-forget.
    """
    for item in batch.errors:
        push_diagnostic(
            {
                "level": (item.severity or "ERROR").upper(),
                "logger": "mbforge.client.errorboundary",
                "message": item.message,
                "exception": item.stack,
                "category": item.category or "client",
                "severity": (item.severity or "ERROR").lower(),
                "error_code": "client_boundary_error",
                "status_code": 0,
                "context": item.context,
            }
        )


class DiagnosticsExportRequest(BaseModel):
    directory: str | None = Field(default=None)
    limit: int = Field(default=200, ge=1, le=5000)


@router.post("/export")
async def export_diagnostics(body: DiagnosticsExportRequest) -> dict[str, Any]:
    """Snapshot the ring buffer + stats to a JSON file on disk.

    The in-memory ring buffer is lost on process restart; this endpoint lets
    operators persist a full snapshot (records + aggregate stats + export
    metadata) before restarting or transferring logs. Writes to
    ``body.directory``, defaulting to the global app ``logs`` directory.
    """
    import asyncio

    from ...services.system.readiness import export_diagnostics_sync

    try:
        return await asyncio.to_thread(
            export_diagnostics_sync, body.directory, body.limit
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"failed to write diagnostics export: {exc}",
        ) from exc

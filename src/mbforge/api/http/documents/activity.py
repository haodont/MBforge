from __future__ import annotations

import anyio
from fastapi import APIRouter, Query
from fastapi import Path as ApiPath
from fastapi.responses import Response

from mbforge.api.http._path_utils import resolve_library_root, validate_doc_id
from mbforge.contracts.measurement import MeasurementDatasetStats
from mbforge.service.dto.activity import ActivityExportRequest, ActivityRecordResponse
from mbforge.service.use_cases.documents.activity_export import (
    export_structure_activity,
)
from mbforge.service.use_cases.documents.activity_queries import (
    dataset_stats,
    list_activity_records,
)

router = APIRouter()


@router.post("/export")
async def export_activities(body: ActivityExportRequest) -> Response:
    root = resolve_library_root(body.library_root)
    for doc_id in body.doc_ids:
        validate_doc_id(doc_id)
    archive = await anyio.to_thread.run_sync(
        export_structure_activity, root, body.doc_ids
    )
    return Response(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="structure-activity.zip"'
        },
    )


@router.get(
    "/documents/{doc_id}",
    response_model=list[ActivityRecordResponse],
)
async def document_activities(
    doc_id: str = ApiPath(..., min_length=1),
    library_root: str | None = Query(default=None),
    target: str = Query(default=""),
    assay_description: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[ActivityRecordResponse]:
    root = resolve_library_root(library_root)
    validate_doc_id(doc_id)
    records = await anyio.to_thread.run_sync(
        list_activity_records,
        str(root),
        doc_id,
        target,
        assay_description,
        limit,
    )
    return [ActivityRecordResponse.model_validate(record) for record in records]


@router.get(
    "/documents/{doc_id}/stats",
    response_model=MeasurementDatasetStats,
)
async def document_activity_stats(
    doc_id: str = ApiPath(..., min_length=1),
    library_root: str | None = Query(default=None),
) -> MeasurementDatasetStats:
    """Coverage of the document's printed readings.

    ``total`` is what the document printed; ``attributed`` is what reached a
    structure. The difference is the extraction backlog, and it is reported
    rather than hidden so a dataset consumer knows what the numbers rest on.
    """
    root = resolve_library_root(library_root)
    validate_doc_id(doc_id)
    return await anyio.to_thread.run_sync(dataset_stats, str(root), doc_id)

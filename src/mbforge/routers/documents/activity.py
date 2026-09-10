from __future__ import annotations

import anyio
from fastapi import APIRouter, Query
from fastapi import Path as ApiPath

from ...models.activity import ActivityRecordResponse
from ...services.documents.activity_queries import list_activity_records
from .._path_utils import resolve_library_root, validate_doc_id

router = APIRouter()


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

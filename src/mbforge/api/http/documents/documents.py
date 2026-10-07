"""Document CRUD endpoints.

List, delete, and re-ingest library documents. Re-ingest clears pipeline
artifacts and re-runs the document through the full processing chain in a
background thread so the API call returns immediately.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from mbforge.api.http._path_utils import resolve_library_root
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.foundation.logger import get_logger
from mbforge.service.dto.documents import (
    DocumentDeleteRequest,
    DocumentDeleteResponse,
    DocumentListRequest,
    DocumentListResponse,
    DocumentPatentAnalysisRequest,
    DocumentPatentAnalysisResponse,
    DocumentReingestRequest,
    DocumentReingestResponse,
)
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.pipeline.ingest import (
    enqueue as ingest_enqueue,
)
from mbforge.service.use_cases.pipeline.ingest import (
    enqueue_patent_analysis,
)

logger = get_logger("mbforge.documents_router")

router = APIRouter()


@router.post("/list")
async def doc_list(body: DocumentListRequest) -> DocumentListResponse:
    root = resolve_library_root(body.library_root)
    if not root:
        raise ValidationError("library_root is required")
    store = LibraryStore.get(str(root))
    docs = await asyncio.to_thread(store.list_documents)
    return DocumentListResponse(documents=[d.to_dict() for d in docs])


@router.post("/delete")
async def doc_delete(body: DocumentDeleteRequest) -> DocumentDeleteResponse:
    root = resolve_library_root(body.library_root)
    store = LibraryStore.get(str(root))
    deleted = await asyncio.to_thread(store.delete_documents, body.doc_ids)
    return DocumentDeleteResponse(deleted=deleted)


@router.post("/reingest")
async def doc_reingest(body: DocumentReingestRequest) -> DocumentReingestResponse:
    root = resolve_library_root(body.library_root)
    if not body.doc_id:
        raise ValidationError("doc_id is required")
    store = LibraryStore.get(str(root))
    doc = store.load_document(body.doc_id)
    if doc is None:
        raise NotFoundError("document not found", detail=f"doc_id={body.doc_id}")
    store.clear_pipeline_data(body.doc_id)
    run_id = await ingest_enqueue(str(root), body.doc_id, force=True)
    return DocumentReingestResponse(run_id=run_id)


@router.post("/patent-analysis")
async def doc_patent_analysis(
    body: DocumentPatentAnalysisRequest,
) -> DocumentPatentAnalysisResponse:
    """Queue a Patent-only analysis run for each eligible document.

    Documents without extracted ``source_evidence`` yet are skipped rather than
    failing the whole batch.
    """
    root = resolve_library_root(body.library_root)
    result = await enqueue_patent_analysis(str(root), body.doc_ids)
    return DocumentPatentAnalysisResponse(
        enqueued=result.updated, skipped=result.skipped
    )

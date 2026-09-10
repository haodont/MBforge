"""Document CRUD endpoints.

List, delete, and re-ingest library documents. Re-ingest clears pipeline
artifacts and re-runs the document through the full processing chain in a
background thread so the API call returns immediately.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from ...models.documents import (
    DocumentDeleteRequest,
    DocumentDeleteResponse,
    DocumentListRequest,
    DocumentListResponse,
    DocumentReingestRequest,
    DocumentReingestResponse,
)
from ...services.documents.library import LibraryStore
from ...services.pipeline.ingest import enqueue as ingest_enqueue
from ...utils.errors import NotFoundError, ValidationError
from ...utils.logger import get_logger
from .._path_utils import resolve_library_root

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
    if not body.doc_id:
        raise ValidationError("doc_id is required")
    store = LibraryStore.get(str(root))
    await asyncio.to_thread(store.delete_document, body.doc_id)
    return DocumentDeleteResponse()


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
    task_id = await ingest_enqueue(str(root), body.doc_id)
    return DocumentReingestResponse(task_id=task_id)

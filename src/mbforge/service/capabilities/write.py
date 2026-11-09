"""Mutating capabilities; every handler requires edit mode at the registry."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from mbforge.foundation.errors import (
    ConflictError,
    NotFoundError,
    PathTraversalError,
    ValidationError,
)
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.pipeline import ingest

_ACTIVE_RUN_STATUSES = {"pending", "processing", "blocked"}


class ImportPdfInput(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    title: str = Field("", max_length=512)


class ImportPdfOutput(BaseModel):
    doc_id: str
    title: str
    file_name: str
    status: str


class SubmitExtractionInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)


class SubmitExtractionOutput(BaseModel):
    run_id: str
    doc_id: str


class ReingestDocumentInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)


class ReingestDocumentOutput(BaseModel):
    run_id: str
    doc_id: str


class RunActionInput(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=128)


class RunActionOutput(BaseModel):
    run_id: str
    updated: int


def _resolve_import_path(library_root: str, raw: str) -> Path:
    """Resolve a path only inside the active library (no arbitrary filesystem)."""
    if not raw.strip():
        raise ValidationError("path is required")
    root = Path(library_root).resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathTraversalError(
            "path escapes the library root", detail=str(resolved)
        ) from exc
    if not resolved.is_file():
        raise NotFoundError("PDF not found", detail=str(resolved))
    return resolved


async def _active_run_id(library_root: str, doc_id: str) -> str | None:
    tasks = await ingest.list_tasks(library_root)
    for task in tasks:
        if task.get("doc_id") == doc_id and task.get("status") in _ACTIVE_RUN_STATUSES:
            return str(task.get("run_id") or "")
    return None


async def import_pdf(
    context: CapabilityContext, request: ImportPdfInput
) -> CapabilityResult:
    path = _resolve_import_path(context.library_root, request.path)
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.add_document, path, request.title)
    return CapabilityResult(data=ImportPdfOutput(**document.to_dict()))


async def submit_extraction(
    context: CapabilityContext, request: SubmitExtractionInput
) -> CapabilityResult:
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)
    active = await _active_run_id(context.library_root, request.doc_id)
    if active:
        raise ConflictError("document already has an active run", detail=active)
    run_id = await ingest.enqueue(context.library_root, request.doc_id)
    return CapabilityResult(
        data=SubmitExtractionOutput(run_id=run_id, doc_id=request.doc_id)
    )


async def reingest_document(
    context: CapabilityContext, request: ReingestDocumentInput
) -> CapabilityResult:
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)
    active = await _active_run_id(context.library_root, request.doc_id)
    if active:
        raise ConflictError("document already has an active run", detail=active)
    await asyncio.to_thread(store.clear_pipeline_data, request.doc_id)
    run_id = await ingest.enqueue(context.library_root, request.doc_id)
    return CapabilityResult(
        data=ReingestDocumentOutput(run_id=run_id, doc_id=request.doc_id)
    )


async def cancel_run(
    context: CapabilityContext, request: RunActionInput
) -> CapabilityResult:
    result = await ingest.cancel_batch(context.library_root, [request.run_id])
    if result.updated == 0:
        raise NotFoundError("run not found", detail=request.run_id)
    return CapabilityResult(
        data=RunActionOutput(run_id=request.run_id, updated=result.updated)
    )


async def retry_run(
    context: CapabilityContext, request: RunActionInput
) -> CapabilityResult:
    result = await ingest.retry_batch(context.library_root, [request.run_id])
    if result.updated == 0:
        raise NotFoundError("run not found", detail=request.run_id)
    return CapabilityResult(
        data=RunActionOutput(run_id=request.run_id, updated=result.updated)
    )


register(
    Capability(
        name="import_pdf",
        description="Register a PDF already inside the active library directory.",
        input_model=ImportPdfInput,
        output_model=ImportPdfOutput,
        mutating=True,
        handler=import_pdf,
    )
)
register(
    Capability(
        name="submit_extraction",
        description="Submit a registered document to the Extract -> Markdown -> Patent pipeline.",
        input_model=SubmitExtractionInput,
        output_model=SubmitExtractionOutput,
        mutating=True,
        handler=submit_extraction,
    )
)
register(
    Capability(
        name="reingest_document",
        description="Clear pipeline outputs and submit the document again.",
        input_model=ReingestDocumentInput,
        output_model=ReingestDocumentOutput,
        mutating=True,
        handler=reingest_document,
    )
)
register(
    Capability(
        name="cancel_run",
        description="Cancel an active pipeline run.",
        input_model=RunActionInput,
        output_model=RunActionOutput,
        mutating=True,
        handler=cancel_run,
    )
)
register(
    Capability(
        name="retry_run",
        description="Retry failed or cancelled nodes of a pipeline run.",
        input_model=RunActionInput,
        output_model=RunActionOutput,
        mutating=True,
        handler=retry_run,
    )
)

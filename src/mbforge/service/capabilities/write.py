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

_document_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _document_lock(library_root: str, doc_id: str) -> asyncio.Lock:
    key = (library_root, doc_id)
    lock = _document_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _document_locks[key] = lock
    return lock


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


class SubmitPatentAnalysisInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)


class SubmitPatentAnalysisOutput(BaseModel):
    doc_id: str
    run_ids: list[str] = Field(default_factory=list)
    enqueued: int
    skipped: int


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
            run_id = task.get("run_id")
            if run_id:
                return str(run_id)
            return None
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
    async with _document_lock(context.library_root, request.doc_id):
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


async def submit_patent_analysis(
    context: CapabilityContext, request: SubmitPatentAnalysisInput
) -> CapabilityResult:
    """Queue the Patent stage once Extract has produced source evidence."""
    from mbforge.service.use_cases.documents.source_evidence import list_evidence

    async with _document_lock(context.library_root, request.doc_id):
        store = LibraryStore.get(context.library_root)
        document = await asyncio.to_thread(store.load_document, request.doc_id)
        if document is None:
            raise NotFoundError("document not found", detail=request.doc_id)
        evidence = await asyncio.to_thread(
            list_evidence, context.library_root, request.doc_id
        )
        if not evidence:
            raise ValidationError(
                "document has no extracted source evidence; run submit_extraction first",
                detail=request.doc_id,
            )
        active = await _active_run_id(context.library_root, request.doc_id)
        if active:
            raise ConflictError("document already has an active run", detail=active)
        result = await ingest.enqueue_patent_analysis(
            context.library_root, [request.doc_id]
        )
    return CapabilityResult(
        data=SubmitPatentAnalysisOutput(
            doc_id=request.doc_id,
            run_ids=result.run_ids,
            enqueued=result.updated,
            skipped=result.skipped,
        )
    )


async def reingest_document(
    context: CapabilityContext, request: ReingestDocumentInput
) -> CapabilityResult:
    async with _document_lock(context.library_root, request.doc_id):
        store = LibraryStore.get(context.library_root)
        document = await asyncio.to_thread(store.load_document, request.doc_id)
        if document is None:
            raise NotFoundError("document not found", detail=request.doc_id)
        source = await asyncio.to_thread(store.resolve_file, request.doc_id)
        if source is None:
            raise NotFoundError("document source file not found", detail=request.doc_id)
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
        description="Submit a registered document to Extract -> Markdown; Patent is a separate opt-in run.",
        input_model=SubmitExtractionInput,
        output_model=SubmitExtractionOutput,
        mutating=True,
        handler=submit_extraction,
    )
)
register(
    Capability(
        name="submit_patent_analysis",
        description="Queue the Patent stage for a document whose Extract evidence exists; poll get_run, then read get_patent_result.",
        input_model=SubmitPatentAnalysisInput,
        output_model=SubmitPatentAnalysisOutput,
        mutating=True,
        handler=submit_patent_analysis,
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

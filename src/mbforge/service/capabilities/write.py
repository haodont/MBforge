"""Mutating capabilities; every handler requires edit mode at the registry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from mbforge.contracts.review_proposal import ReviewProposal, ReviewProposalResult
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
    doc_id_field,
    register,
)
from mbforge.service.use_cases import review_proposals
from mbforge.service.use_cases.documents.document_refs import short_doc_id
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
    path: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description=(
            "PDF path inside the active library; relative paths resolve against "
            "the library root."
        ),
    )
    title: str = Field("", max_length=512, description="Optional document title.")


class ImportPdfOutput(BaseModel):
    doc_id: str
    short_id: str
    title: str
    file_name: str
    status: str
    run_id: str | None = None


class SubmitExtractionInput(BaseModel):
    doc_id: str = doc_id_field()


class SubmitExtractionOutput(BaseModel):
    run_id: str
    doc_id: str
    short_id: str


class SubmitPatentAnalysisInput(BaseModel):
    doc_id: str = doc_id_field()


class SubmitPatentAnalysisOutput(BaseModel):
    doc_id: str
    short_id: str
    run_ids: list[str] = Field(default_factory=list)
    enqueued: int
    skipped: int


class ReingestDocumentInput(BaseModel):
    doc_id: str = doc_id_field()


class ReingestDocumentOutput(BaseModel):
    run_id: str
    doc_id: str
    short_id: str


class RunActionInput(BaseModel):
    action: Literal["cancel", "retry"] = Field(
        ...,
        description=(
            "`cancel` stops an active run; `retry` re-queues its failed or "
            "cancelled nodes."
        ),
    )
    run_id: str = Field(
        ..., min_length=1, max_length=128, description="Pipeline run id."
    )


class RunActionOutput(BaseModel):
    action: Literal["cancel", "retry"]
    run_id: str
    updated: int


class ProposeReviewInput(BaseModel):
    items: list[ReviewProposal] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Proposals a human will confirm or reject; nothing is applied.",
    )


class ProposeReviewOutput(BaseModel):
    items: list[ReviewProposalResult] = Field(default_factory=list)


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
    run_id = await ingest.auto_enqueue_on_import(context.library_root, document.doc_id)
    return CapabilityResult(
        data=ImportPdfOutput(
            **document.to_dict(),
            short_id=short_doc_id(document.doc_id),
            run_id=run_id,
        )
    )


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
        data=SubmitExtractionOutput(
            run_id=run_id,
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id),
        )
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
            short_id=short_doc_id(request.doc_id),
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
        data=ReingestDocumentOutput(
            run_id=run_id,
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id),
        )
    )


async def run_control(
    context: CapabilityContext, request: RunActionInput
) -> CapabilityResult:
    """Cancel or retry one run; both act on the same queue rows."""
    batch = ingest.cancel_batch if request.action == "cancel" else ingest.retry_batch
    result = await batch(context.library_root, [request.run_id])
    if result.updated == 0:
        raise NotFoundError("run not found", detail=request.run_id)
    return CapabilityResult(
        data=RunActionOutput(
            action=request.action, run_id=request.run_id, updated=result.updated
        )
    )


async def propose_review(
    context: CapabilityContext, request: ProposeReviewInput
) -> CapabilityResult:
    """Record agent proposals; a human still confirms or rejects every one."""
    results = await asyncio.to_thread(
        review_proposals.propose_items, context.library_root, request.items
    )
    return CapabilityResult(data=ProposeReviewOutput(items=results))


register(
    Capability(
        name="import_pdf",
        description=(
            "Register a PDF already inside the active library directory and, "
            "unless ingest.auto_enqueue_on_import is disabled, queue Extract -> "
            "Markdown. Returns run_id (null when not queued or the enqueue "
            "failed); continue with submit_patent_analysis for Patent."
        ),
        input_model=ImportPdfInput,
        output_model=ImportPdfOutput,
        mutating=True,
        handler=import_pdf,
    )
)
register(
    Capability(
        name="submit_extraction",
        description=(
            "Submit a registered document to Extract -> Markdown; Patent is a "
            "separate opt-in run. The CLI notifies the session when the run "
            "ends, so do not poll get_run."
        ),
        input_model=SubmitExtractionInput,
        output_model=SubmitExtractionOutput,
        mutating=True,
        handler=submit_extraction,
    )
)
register(
    Capability(
        name="submit_patent_analysis",
        description=(
            "Queue the Patent stage for a document whose Extract evidence "
            "exists. The CLI notifies the session when it ends; then read "
            "get_patent_result."
        ),
        input_model=SubmitPatentAnalysisInput,
        output_model=SubmitPatentAnalysisOutput,
        mutating=True,
        handler=submit_patent_analysis,
    )
)
register(
    Capability(
        name="reingest_document",
        description=(
            "Clear pipeline outputs and submit the document again. The CLI "
            "notifies the session when the run ends."
        ),
        input_model=ReingestDocumentInput,
        output_model=ReingestDocumentOutput,
        mutating=True,
        handler=reingest_document,
    )
)
register(
    Capability(
        name="run_control",
        description=(
            "Act on one pipeline run: action=cancel stops an active run, "
            "action=retry re-queues its failed or cancelled nodes."
        ),
        input_model=RunActionInput,
        output_model=RunActionOutput,
        mutating=True,
        handler=run_control,
    )
)
register(
    Capability(
        name="propose_review",
        description=(
            "File review proposals for a human decision; never applies a value "
            "and refuses targets a human already decided."
        ),
        input_model=ProposeReviewInput,
        output_model=ProposeReviewOutput,
        mutating=True,
        handler=propose_review,
    )
)

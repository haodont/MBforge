"""Read-only capabilities exposed to agents."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from mbforge.foundation.errors import NotFoundError
from mbforge.foundation.layout import LibraryLayout
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.use_cases.documents import source_evidence
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.documents.patent_facts import load_patent_facts
from mbforge.service.use_cases.molecule.queries import search_molecules
from mbforge.service.use_cases.pipeline import ingest


class DocumentMatch(BaseModel):
    doc_id: str
    title: str
    file_name: str
    page_count: int
    status: str


class ResolveDocumentInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    limit: int = Field(5, ge=1, le=20)


class ResolveDocumentOutput(BaseModel):
    matches: list[DocumentMatch]


class GetDocumentInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)


class GetDocumentOutput(BaseModel):
    doc_id: str
    title: str
    file_name: str
    page_count: int
    status: str
    created_at: str
    has_markdown: bool
    has_patent_facts: bool


class GetDocumentMarkdownInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    offset: int = Field(0, ge=0)
    max_chars: int = Field(20000, ge=1000, le=200000)


class GetDocumentMarkdownOutput(BaseModel):
    doc_id: str
    content: str
    offset: int
    next_offset: int | None


class ListEvidenceInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    page: int | None = Field(None, ge=1)
    kind: str | None = Field(None, max_length=32)
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=200)


class EvidenceItem(BaseModel):
    evidence_id: str
    page: int
    kind: str
    raw_text: str
    bbox: list[float]


class ListEvidenceOutput(BaseModel):
    items: list[EvidenceItem]


class GetPatentResultInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    offset: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=100)


class PatentFactCounts(BaseModel):
    sections: int
    entries: int
    synthesis_steps: int
    assay_methods: int
    examples: int
    measurements: int
    issues: int


class GetPatentResultOutput(BaseModel):
    doc_id: str
    run_id: str
    stats: dict[str, Any]
    counts: PatentFactCounts
    sections: list[dict[str, Any]]
    entries: list[dict[str, Any]]


class SearchMoleculesInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    mode: Literal["auto", "text", "substructure", "similarity"] = "auto"
    top_k: int = Field(10, ge=1, le=50)
    similarity_threshold: float = Field(0.5, ge=0.0, le=1.0)


class SearchMoleculesOutput(BaseModel):
    items: list[dict[str, Any]]


class GetRunInput(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=128)


class RunNode(BaseModel):
    stage: str
    status: str


class GetRunOutput(BaseModel):
    run_id: str
    doc_id: str | None
    status: str
    nodes: list[RunNode]


async def resolve_document(
    context: CapabilityContext, request: ResolveDocumentInput
) -> CapabilityResult:
    def _search() -> list[dict[str, Any]]:
        store = LibraryStore.get(context.library_root)
        exact = store.load_document(request.query)
        documents = (
            [exact] if exact is not None else store.search_documents(request.query)
        )
        return [document.to_dict() for document in documents]

    rows = await asyncio.to_thread(_search)
    truncated = len(rows) > request.limit
    return CapabilityResult(
        data=ResolveDocumentOutput(
            matches=[DocumentMatch(**row) for row in rows[: request.limit]]
        ),
        truncated=truncated,
    )


async def get_document(
    context: CapabilityContext, request: GetDocumentInput
) -> CapabilityResult:
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)

    layout = LibraryLayout(context.library_root)
    payload = document.to_dict()
    payload["has_markdown"] = layout.document_md(request.doc_id).is_file()
    payload["has_patent_facts"] = (
        layout.storage_dir(request.doc_id) / "patent_facts.json"
    ).is_file()
    return CapabilityResult(data=GetDocumentOutput(**payload))


async def get_document_markdown(
    context: CapabilityContext, request: GetDocumentMarkdownInput
) -> CapabilityResult:
    path = LibraryLayout(context.library_root).document_md(request.doc_id)
    if not path.is_file():
        raise NotFoundError("document markdown not available", detail=request.doc_id)
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    chunk = text[request.offset : request.offset + request.max_chars]
    next_offset = (
        request.offset + request.max_chars
        if request.offset + request.max_chars < len(text)
        else None
    )
    return CapabilityResult(
        data=GetDocumentMarkdownOutput(
            doc_id=request.doc_id,
            content=chunk,
            offset=request.offset,
            next_offset=next_offset,
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def list_evidence(
    context: CapabilityContext, request: ListEvidenceInput
) -> CapabilityResult:
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)
    records = await asyncio.to_thread(
        source_evidence.list_evidence,
        context.library_root,
        request.doc_id,
        request.page,
        request.kind,
    )
    page = records[request.offset : request.offset + request.limit]
    next_offset = (
        request.offset + request.limit
        if request.offset + request.limit < len(records)
        else None
    )
    return CapabilityResult(
        data=ListEvidenceOutput(
            items=[EvidenceItem(**record.to_dict()) for record in page]
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def get_patent_result(
    context: CapabilityContext, request: GetPatentResultInput
) -> CapabilityResult:
    facts = await asyncio.to_thread(
        load_patent_facts, context.library_root, request.doc_id
    )
    if facts is None:
        raise NotFoundError("patent facts not available", detail=request.doc_id)

    entries = facts.entries[request.offset : request.offset + request.limit]
    next_offset = (
        request.offset + request.limit
        if request.offset + request.limit < len(facts.entries)
        else None
    )
    counts = PatentFactCounts(
        sections=len(facts.sections),
        entries=len(facts.entries),
        synthesis_steps=len(facts.synthesis_steps),
        assay_methods=len(facts.assay_methods),
        examples=len(facts.examples),
        measurements=len(facts.measurements),
        issues=len(facts.issues),
    )
    return CapabilityResult(
        data=GetPatentResultOutput(
            doc_id=facts.doc_id,
            run_id=facts.run_id,
            stats=facts.stats,
            counts=counts,
            sections=[section.model_dump() for section in facts.sections],
            entries=entries,
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def search_molecules_capability(
    context: CapabilityContext, request: SearchMoleculesInput
) -> CapabilityResult:
    items = await asyncio.to_thread(
        search_molecules,
        context.library_root,
        request.query,
        request.top_k,
        request.mode,
        request.similarity_threshold,
    )
    return CapabilityResult(data=SearchMoleculesOutput(items=items))


async def get_run(context: CapabilityContext, request: GetRunInput) -> CapabilityResult:
    tasks = await ingest.list_tasks(context.library_root)
    rows = [task for task in tasks if task.get("run_id") == request.run_id]
    if not rows:
        raise NotFoundError("run not found", detail=request.run_id)

    status = await asyncio.to_thread(
        ingest.fetch_run_status, context.library_root, request.run_id
    )
    return CapabilityResult(
        data=GetRunOutput(
            run_id=request.run_id,
            doc_id=rows[0].get("doc_id"),
            status=status or "unknown",
            nodes=[
                RunNode(
                    stage=str(row.get("stage") or ""),
                    status=str(row.get("status") or ""),
                )
                for row in rows
            ],
        )
    )


register(
    Capability(
        name="resolve_document",
        description="Find library documents by exact doc_id or by title/file-name substring.",
        input_model=ResolveDocumentInput,
        output_model=ResolveDocumentOutput,
        mutating=False,
        handler=resolve_document,
    )
)
register(
    Capability(
        name="get_document",
        description="Return one document's metadata and whether Markdown/Patent facts exist.",
        input_model=GetDocumentInput,
        output_model=GetDocumentOutput,
        mutating=False,
        handler=get_document,
    )
)
register(
    Capability(
        name="get_document_markdown",
        description="Read a chunk of the assembled document Markdown.",
        input_model=GetDocumentMarkdownInput,
        output_model=GetDocumentMarkdownOutput,
        mutating=False,
        handler=get_document_markdown,
    )
)
register(
    Capability(
        name="list_evidence",
        description="List canonical source evidence for one document page or kind.",
        input_model=ListEvidenceInput,
        output_model=ListEvidenceOutput,
        mutating=False,
        handler=list_evidence,
    )
)
register(
    Capability(
        name="get_patent_result",
        description="Return Patent facts summary plus a page of compound entries.",
        input_model=GetPatentResultInput,
        output_model=GetPatentResultOutput,
        mutating=False,
        handler=get_patent_result,
    )
)
register(
    Capability(
        name="search_molecules",
        description="Search the active molecule library by text, substructure, or similarity.",
        input_model=SearchMoleculesInput,
        output_model=SearchMoleculesOutput,
        mutating=False,
        handler=search_molecules_capability,
    )
)
register(
    Capability(
        name="get_run",
        description="Return one pipeline run's aggregated status and stage nodes.",
        input_model=GetRunInput,
        output_model=GetRunOutput,
        mutating=False,
        handler=get_run,
    )
)

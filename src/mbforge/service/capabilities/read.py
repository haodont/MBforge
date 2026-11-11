"""Read-only document and evidence capabilities exposed to agents.

Patent facts, molecule search, and page/structure visual actions live in the
sibling ``read_patent``, ``read_molecules`` and ``read_visual`` modules.
"""

from __future__ import annotations

import asyncio
from typing import Any, get_args

from pydantic import BaseModel, Field

from mbforge.contracts.measurement import ReviewStatus as MeasurementReviewStatus
from mbforge.domain.evidence_kind import CATEGORIES
from mbforge.domain.patent import (
    ROLE_COMPOUND,
    ROLE_EXAMPLE,
    ROLE_INTERMEDIATE,
    ROLE_PREPARATION,
    ROLE_REAGENT,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RESOLVED,
    STRUCTURE_MISSING,
    STRUCTURE_PENDING,
    STRUCTURE_RESOLVED,
)
from mbforge.domain.review import APPROVED, PENDING, REJECTED
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.foundation.layout import LibraryLayout
from mbforge.service.capabilities.registry import (
    DOC_ID_DESCRIPTION,
    Capability,
    CapabilityContext,
    CapabilityResult,
    doc_id_field,
    register,
)
from mbforge.service.dto.review import ReviewKind
from mbforge.service.pipeline.layout.labels import kind_vocab
from mbforge.service.pipeline.patent.sections import SECTION_KINDS
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents import source_evidence
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.pipeline import ingest


class DocumentMatch(BaseModel):
    doc_id: str
    short_id: str
    title: str
    file_name: str
    page_count: int
    status: str


class ResolveDocumentInput(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Title, file name, full doc_id, or a unique doc_id prefix.",
    )
    limit: int = Field(5, ge=1, le=20, description="Maximum matches to return.")


class ResolveDocumentOutput(BaseModel):
    matches: list[DocumentMatch]


class GetDocumentInput(BaseModel):
    doc_id: str = doc_id_field()


class GetDocumentOutput(BaseModel):
    doc_id: str
    short_id: str = Field(
        ...,
        description="12-character display id; use it in prose, not for links.",
    )
    title: str
    file_name: str = Field(
        ...,
        description=(
            "Stored PDF filename under storage/{doc_id}/; use this exact name, "
            "never assume source.pdf."
        ),
    )
    page_count: int
    status: str
    created_at: str
    has_markdown: bool
    has_patent_facts: bool


class GetDocumentMarkdownInput(BaseModel):
    doc_id: str = doc_id_field()
    offset: int = Field(0, ge=0, description="Character offset into document.md.")
    max_chars: int = Field(
        20000,
        ge=1000,
        le=200000,
        description="Maximum characters to return in this page.",
    )


class GetDocumentMarkdownOutput(BaseModel):
    doc_id: str
    short_id: str
    content: str
    offset: int
    next_offset: int | None


class ListEvidenceInput(BaseModel):
    doc_id: str = doc_id_field()
    page: int | None = Field(
        None, ge=1, description="Restrict to one 1-based PDF page."
    )
    kind: str | None = Field(
        None,
        max_length=32,
        description=(
            "Producer label to filter; call get_vocabulary for the closed set. "
            "An unknown kind is rejected."
        ),
    )
    offset: int = Field(0, ge=0, description="Number of matching rows to skip.")
    limit: int = Field(50, ge=1, le=200, description="Maximum evidence rows to return.")


class EvidenceItem(BaseModel):
    evidence_id: str
    page: int
    kind: str
    raw_text: str
    bbox: list[float]


class ListEvidenceOutput(BaseModel):
    doc_id: str = Field(
        ...,
        description="Canonical document id these evidence rows belong to.",
    )
    short_id: str = Field(
        ...,
        description="12-character display id for the same document.",
    )
    items: list[EvidenceItem]


class GetRunInput(BaseModel):
    run_id: str = Field(
        ..., min_length=1, max_length=128, description="Pipeline run id."
    )


class RunNode(BaseModel):
    stage: str
    status: str


class GetRunOutput(BaseModel):
    run_id: str
    doc_id: str | None
    short_id: str | None = None
    status: str
    nodes: list[RunNode]


class SearchEvidenceInput(BaseModel):
    """Literal keyword search over canonical source evidence across documents."""

    query: str = Field(..., min_length=1, max_length=400)
    doc_id: str = Field("", max_length=128, description=DOC_ID_DESCRIPTION)
    offset: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=50)


class EvidenceMatch(BaseModel):
    evidence_id: str
    doc_id: str
    short_id: str
    page: int
    kind: str
    title: str
    file_name: str
    snippet: str
    truncated: bool


class SearchEvidenceOutput(BaseModel):
    items: list[EvidenceMatch]


class GetVocabularyInput(BaseModel):
    """No parameters: the vocabularies are library-independent."""


class GetVocabularyOutput(BaseModel):
    """Every closed label set an agent may pass or receive.

    These are the vocabularies the pipeline mints; nothing here is a guess from
    observed rows. ``evidence_kinds`` maps each producer label to its category,
    and an unknown ``kind`` filter is rejected rather than answered with an
    empty page. The two review vocabularies differ by store on purpose.
    """

    evidence_kinds: dict[str, str]
    evidence_categories: list[str]
    section_kinds: list[str]
    entry_roles: list[str]
    structure_statuses: list[str]
    fact_statuses: list[str]
    molecule_review_statuses: list[str]
    measurement_review_statuses: list[str]
    review_kinds: list[str]


async def resolve_document(
    context: CapabilityContext, request: ResolveDocumentInput
) -> CapabilityResult:
    def _search() -> list[dict[str, Any]]:
        store = LibraryStore.get(context.library_root)
        exact = store.load_document(request.query)
        documents = (
            [exact]
            if exact is not None
            else store.search_documents(request.query, limit=request.limit + 1)
        )
        return [document.to_dict() for document in documents]

    rows = await asyncio.to_thread(_search)
    truncated = len(rows) > request.limit
    return CapabilityResult(
        data=ResolveDocumentOutput(
            matches=[
                DocumentMatch(
                    **row,
                    short_id=short_doc_id(str(row["doc_id"])),
                )
                for row in rows[: request.limit]
            ]
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
    payload["short_id"] = short_doc_id(document.doc_id)
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
            short_id=short_doc_id(request.doc_id),
            content=chunk,
            offset=request.offset,
            next_offset=next_offset,
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


def _require_known_kind(kind: str) -> None:
    """Reject a ``kind`` no producer mints instead of answering with an empty page."""
    vocabulary = kind_vocab()
    if kind not in vocabulary:
        raise ValidationError(
            "unknown evidence kind",
            detail=kind,
            context={"valid_kinds": sorted(vocabulary)},
        )


async def list_evidence(
    context: CapabilityContext, request: ListEvidenceInput
) -> CapabilityResult:
    if request.kind is not None:
        _require_known_kind(request.kind)
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
        limit=request.limit + 1,
        offset=request.offset,
    )
    truncated = len(records) > request.limit
    page = records[: request.limit]
    next_offset = request.offset + request.limit if truncated else None
    return CapabilityResult(
        data=ListEvidenceOutput(
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id),
            items=[EvidenceItem(**record.to_dict()) for record in page],
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def get_run(context: CapabilityContext, request: GetRunInput) -> CapabilityResult:
    rows = await ingest.list_run_tasks(context.library_root, request.run_id)
    if not rows:
        raise NotFoundError("run not found", detail=request.run_id)

    status = await asyncio.to_thread(
        ingest.fetch_run_status, context.library_root, request.run_id
    )
    doc_id = rows[0].get("doc_id")
    return CapabilityResult(
        data=GetRunOutput(
            run_id=request.run_id,
            doc_id=doc_id,
            short_id=short_doc_id(str(doc_id)) if doc_id else None,
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


async def search_evidence(
    context: CapabilityContext, request: SearchEvidenceInput
) -> CapabilityResult:
    """Search extracted SQL evidence without loading the whole library."""
    rows = await asyncio.to_thread(
        get_repositories(context.library_root).evidence.search,
        request.query,
        doc_id=request.doc_id,
        limit=request.limit + 1,
        offset=request.offset,
    )
    truncated = len(rows) > request.limit
    page = rows[: request.limit]
    return CapabilityResult(
        data=SearchEvidenceOutput(
            items=[
                EvidenceMatch(**row, short_id=short_doc_id(str(row["doc_id"])))
                for row in page
            ]
        ),
        truncated=truncated,
        next_offset=request.offset + request.limit if truncated else None,
    )


async def get_vocabulary(
    context: CapabilityContext, request: GetVocabularyInput
) -> CapabilityResult:
    """Report the closed label sets the pipeline mints."""
    return CapabilityResult(
        data=GetVocabularyOutput(
            evidence_kinds=dict(sorted(kind_vocab().items())),
            evidence_categories=sorted(CATEGORIES),
            section_kinds=list(SECTION_KINDS),
            entry_roles=[
                ROLE_EXAMPLE,
                ROLE_PREPARATION,
                ROLE_COMPOUND,
                ROLE_INTERMEDIATE,
                ROLE_REAGENT,
            ],
            structure_statuses=[
                STRUCTURE_MISSING,
                STRUCTURE_PENDING,
                STRUCTURE_RESOLVED,
            ],
            fact_statuses=[STATUS_PENDING, STATUS_RESOLVED, STATUS_FAILED],
            molecule_review_statuses=[PENDING, APPROVED, REJECTED],
            measurement_review_statuses=list(get_args(MeasurementReviewStatus)),
            review_kinds=list(get_args(ReviewKind)),
        )
    )


register(
    Capability(
        name="resolve_document",
        description=(
            "Find library documents by exact doc_id or by title/file-name "
            "substring. Each match carries a short_id — the first 12 hex "
            "characters of its doc_id — which every other capability accepts "
            "in place of the full doc_id, as do the exact title and file name."
        ),
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
        description="Read a chunk of the assembled document Markdown. Narrative text only; use query_activities for structured activity readings.",
        input_model=GetDocumentMarkdownInput,
        output_model=GetDocumentMarkdownOutput,
        mutating=False,
        handler=get_document_markdown,
    )
)


register(
    Capability(
        name="list_evidence",
        description="List canonical source evidence for one document page or kind. kind must be a label the producers mint — call get_vocabulary for that set; an unregistered kind is rejected instead of answered with an empty page. For kind=molecule the raw_text is a JSON envelope, not printed text.",
        input_model=ListEvidenceInput,
        output_model=ListEvidenceOutput,
        mutating=False,
        handler=list_evidence,
    )
)


register(
    Capability(
        name="get_vocabulary",
        description=(
            "Return every closed label set an agent may pass or receive: "
            "evidence kind → category, Patent section kinds, compound entry "
            "roles, structure/fact lifecycle values and the two review "
            "vocabularies. Call this before filtering by kind or reading a "
            "status instead of guessing; a wrong guess returns an empty page, "
            "not an error."
        ),
        input_model=GetVocabularyInput,
        output_model=GetVocabularyOutput,
        mutating=False,
        handler=get_vocabulary,
    )
)


register(
    Capability(
        name="search_evidence",
        description="Search extracted SQL source text across documents; returns bounded snippets with document, page, kind and pagination. An empty result does not prove absence. Use query_activities for structured activity values.",
        input_model=SearchEvidenceInput,
        output_model=SearchEvidenceOutput,
        mutating=False,
        handler=search_evidence,
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

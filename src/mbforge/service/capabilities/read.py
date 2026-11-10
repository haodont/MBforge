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
from mbforge.service.ports import get_repositories
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


class SearchEvidenceInput(BaseModel):
    """Literal keyword search over canonical source evidence across documents."""

    query: str = Field(..., min_length=1, max_length=400)
    doc_id: str = Field("", max_length=128)
    offset: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=50)


class EvidenceMatch(BaseModel):
    evidence_id: str
    doc_id: str
    page: int
    kind: str
    title: str
    file_name: str
    snippet: str
    truncated: bool


class SearchEvidenceOutput(BaseModel):
    items: list[EvidenceMatch]


class RecognizeMoleculesInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    page: int = Field(..., ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    max_molecules: int = Field(10, ge=1, le=20)


class RecognizeMoleculesOutput(BaseModel):
    page: int
    page_width_pts: float
    page_height_pts: float
    dpi: float
    region: list[float] | None = None
    count: int
    truncated: bool
    molecules: list[dict[str, Any]]


class PageTextBlock(BaseModel):
    region_id: str
    kind: str
    type: str
    bbox_pdf: list[float]
    reading_order: int
    text: str


class OcrPageRegionInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    page: int = Field(1, ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    max_blocks: int = Field(50, ge=1, le=100)


class OcrPageRegionOutput(BaseModel):
    doc_id: str
    page: int
    page_width_pts: float
    page_height_pts: float
    dpi: float
    region: list[float] | None = None
    count: int
    truncated: bool
    text: str
    blocks: list[PageTextBlock]


class RecognizeStructureImageInput(BaseModel):
    image_base64: str = Field(..., min_length=1, max_length=12_000_000)


class RecognizeStructureImageOutput(BaseModel):
    smiles: str
    esmiles: str
    coref: list[str] = Field(default_factory=list)
    coref_primary: str
    recognized: bool


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
        limit=request.limit + 1,
        offset=request.offset,
    )
    truncated = len(records) > request.limit
    page = records[: request.limit]
    next_offset = request.offset + request.limit if truncated else None
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
    rows = await ingest.list_run_tasks(context.library_root, request.run_id)
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
        data=SearchEvidenceOutput(items=[EvidenceMatch(**row) for row in page]),
        truncated=truncated,
        next_offset=request.offset + request.limit if truncated else None,
    )


async def recognize_molecules_capability(
    context: CapabilityContext, request: RecognizeMoleculesInput
) -> CapabilityResult:
    """Run the local MolDet + MolParser pass over one page or region."""
    from mbforge.service.use_cases.molecule.recognition import (
        recognize_page_molecules,
    )

    store = LibraryStore.get(context.library_root)
    pdf_path = await asyncio.to_thread(store.resolve_file, request.doc_id)
    if pdf_path is None:
        raise NotFoundError("document source file not found", detail=request.doc_id)
    result = await asyncio.to_thread(
        recognize_page_molecules,
        pdf_path,
        page=request.page,
        region=request.region,
        max_molecules=request.max_molecules,
    )
    return CapabilityResult(data=RecognizeMoleculesOutput(**result))


def _decode_structure_image(payload: str) -> Any:
    """Decode one base64 image without touching the library or filesystem."""
    import base64
    import io

    from PIL import Image

    from mbforge.foundation.errors import ValidationError

    encoded = payload.strip()
    if encoded.startswith("data:"):
        _, _, encoded = encoded.partition(",")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001 - malformed client input
        raise ValidationError("image_base64 is not valid base64") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise ValidationError("image_base64 decodes to more than 8 MiB")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:  # noqa: BLE001 - malformed client input
        raise ValidationError("image_base64 is not a readable image") from exc
    if image.width > 4096 or image.height > 4096:
        raise ValidationError("image dimensions must not exceed 4096x4096")
    return image.convert("RGB")


async def recognize_structure_image_capability(
    context: CapabilityContext, request: RecognizeStructureImageInput
) -> CapabilityResult:
    """Recognize one cropped structure image supplied by the caller."""
    from mbforge.service.pipeline.detection.recognition import recognize_molecule

    image = await asyncio.to_thread(_decode_structure_image, request.image_base64)
    result = await asyncio.to_thread(recognize_molecule, image)
    return CapabilityResult(
        data=RecognizeStructureImageOutput(
            smiles=result.smiles,
            esmiles=result.esmiles,
            coref=result.coref,
            coref_primary=result.coref_primary,
            recognized=bool(result.smiles or result.esmiles),
        )
    )


async def ocr_page_region_capability(
    context: CapabilityContext, request: OcrPageRegionInput
) -> CapabilityResult:
    """Read layout text from one stored page, optionally one PDF region."""
    from mbforge.service.use_cases.documents.page_text import ocr_page_region

    store = LibraryStore.get(context.library_root)
    pdf_path = await asyncio.to_thread(store.resolve_file, request.doc_id)
    if pdf_path is None:
        raise NotFoundError("document source file not found", detail=request.doc_id)
    result = await asyncio.to_thread(
        ocr_page_region,
        pdf_path,
        doc_id=request.doc_id,
        page=request.page,
        region=request.region,
        max_blocks=request.max_blocks,
    )
    return CapabilityResult(data=OcrPageRegionOutput(**result))


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
        name="search_evidence",
        description="Search extracted SQL source text across documents; returns bounded snippets with document, page, kind and pagination. An empty result does not prove absence.",
        input_model=SearchEvidenceInput,
        output_model=SearchEvidenceOutput,
        mutating=False,
        handler=search_evidence,
    )
)
register(
    Capability(
        name="recognize_molecules",
        description="Run the local MolDet + MolParser recognizers over one page (optionally one PDF-point region) of a stored document; returns SMILES/E-SMILES, bboxes and printed labels without persisting.",
        input_model=RecognizeMoleculesInput,
        output_model=RecognizeMoleculesOutput,
        mutating=False,
        handler=recognize_molecules_capability,
    )
)
register(
    Capability(
        name="ocr_page_region",
        description="Read layout-guided local text from one page of a stored document, optionally one PDF-point region; returns text blocks and bboxes without persisting.",
        input_model=OcrPageRegionInput,
        output_model=OcrPageRegionOutput,
        mutating=False,
        handler=ocr_page_region_capability,
    )
)
register(
    Capability(
        name="recognize_structure_image",
        description="Recognize one base64-encoded structure image with MolParser and read its printed labels; nothing is persisted.",
        input_model=RecognizeStructureImageInput,
        output_model=RecognizeStructureImageOutput,
        mutating=False,
        handler=recognize_structure_image_capability,
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

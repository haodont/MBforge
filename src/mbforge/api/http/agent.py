"""Tool endpoints the MBForge agent sidecar calls back into.

The browser streams chat from the `agent/` Node sidecar; that sidecar reaches
these endpoints to read library facts, so nothing here talks to an LLM. Every
endpoint resolves the active library server-side — the model never chooses a
path — and reads through the use-case layer, never the concrete adapter.

Tools:
    molecule-search   semantic / structural molecule lookup (existing)
    library-stats     coarse counts across the library's tables
    query-documents   list / filter documents
    query-activities  a document's Patent-stage activity measurements
    query-evidence    a document's source-evidence rows
    search-library    cross-document extracted text search
    library-sql       guarded read-only SELECT escape hatch
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from mbforge.api.http._path_utils import resolve_library_root, resolve_pdf_path
from mbforge.foundation.errors import ValidationError
from mbforge.service.use_cases.agent_queries import (
    library_schema,
    library_stats,
    query_activities,
    query_documents,
    query_evidence,
    run_library_sql,
    search_library,
)
from mbforge.service.use_cases.molecule.queries import search_molecules

router = APIRouter()


# ---------------------------------------------------------------------------
# molecule_search
# ---------------------------------------------------------------------------
class AgentMoleculeSearchRequest(BaseModel):
    """Safe tool input: the active library is resolved server-side."""

    query: str = Field(..., min_length=1, max_length=512)
    mode: Literal["auto", "text", "substructure", "similarity"] = "auto"
    top_k: int = Field(10, ge=1, le=20)
    similarity_threshold: float = Field(0.5, ge=0.0, le=1.0)


class AgentMoleculeSearchResponse(BaseModel):
    success: bool = True
    tool: Literal["molecule_search"] = "molecule_search"
    results: list[dict] = Field(default_factory=list)


@router.post("/tools/molecule-search", response_model=AgentMoleculeSearchResponse)
async def agent_molecule_search(
    body: AgentMoleculeSearchRequest,
) -> AgentMoleculeSearchResponse:
    """Search the configured library for the agent's molecule_search tool."""

    results = await asyncio.to_thread(
        search_molecules,
        str(resolve_library_root(None)),
        body.query,
        top_k=body.top_k,
        mode=body.mode,
        similarity_threshold=body.similarity_threshold,
    )
    return AgentMoleculeSearchResponse(results=results)


# ---------------------------------------------------------------------------
# Structured library queries
# ---------------------------------------------------------------------------
class AgentLibraryStatsResponse(BaseModel):
    success: bool = True
    tool: Literal["library_stats"] = "library_stats"
    stats: dict = Field(default_factory=dict)


@router.post("/tools/library-stats", response_model=AgentLibraryStatsResponse)
async def agent_library_stats() -> AgentLibraryStatsResponse:
    """Coarse record counts across the library's main tables."""

    stats = await asyncio.to_thread(library_stats, str(resolve_library_root(None)))
    return AgentLibraryStatsResponse(stats=stats)


class AgentQueryDocumentsRequest(BaseModel):
    status: str = Field("", max_length=64)
    name: str = Field("", max_length=256)
    limit: int = Field(50, ge=1, le=200)


class AgentResultsResponse(BaseModel):
    success: bool = True
    tool: str
    results: list[dict] = Field(default_factory=list)


class AgentSearchLibraryRequest(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(min_length=1, max_length=400)
    doc_id: str = Field("", max_length=128)
    limit: int = Field(20, ge=1, le=50)
    offset: int = Field(0, ge=0, le=10000)


@router.post("/tools/search-library")
async def agent_search_library(body: AgentSearchLibraryRequest) -> dict[str, Any]:
    return await asyncio.to_thread(
        search_library, str(resolve_library_root(None)), **body.model_dump()
    )


@router.post("/tools/query-documents", response_model=AgentResultsResponse)
async def agent_query_documents(
    body: AgentQueryDocumentsRequest,
) -> AgentResultsResponse:
    """List / filter the library's documents."""

    results = await asyncio.to_thread(
        query_documents,
        str(resolve_library_root(None)),
        status=body.status,
        name=body.name,
        limit=body.limit,
    )
    return AgentResultsResponse(tool="query_documents", results=results)


class AgentQueryActivitiesRequest(BaseModel):
    #: Optional: an empty doc_id asks the whole library.
    doc_id: str = Field("", max_length=256)
    target: str = Field("", max_length=256)
    assay_description: str = Field("", max_length=256)
    metric: str = Field("", max_length=64)
    min_value: float | None = None
    max_value: float | None = None
    limit: int = Field(50, ge=1, le=200)


@router.post("/tools/query-activities", response_model=AgentResultsResponse)
async def agent_query_activities(
    body: AgentQueryActivitiesRequest,
) -> AgentResultsResponse:
    """Return a document's activity measurements."""

    results = await asyncio.to_thread(
        query_activities,
        str(resolve_library_root(None)),
        doc_id=body.doc_id,
        target=body.target,
        assay_description=body.assay_description,
        metric=body.metric,
        min_value=body.min_value,
        max_value=body.max_value,
        limit=body.limit,
    )
    return AgentResultsResponse(tool="query_activities", results=results)


class AgentQueryEvidenceRequest(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=256)
    page: int | None = Field(None, ge=1)
    kind: str = Field("", max_length=64)
    text: str = Field("", max_length=512)
    limit: int = Field(50, ge=1, le=200)


@router.post("/tools/query-evidence", response_model=AgentResultsResponse)
async def agent_query_evidence(
    body: AgentQueryEvidenceRequest,
) -> AgentResultsResponse:
    """Return a document's source-evidence rows."""

    results = await asyncio.to_thread(
        query_evidence,
        str(resolve_library_root(None)),
        doc_id=body.doc_id,
        page=body.page,
        kind=body.kind,
        text=body.text,
        limit=body.limit,
    )
    return AgentResultsResponse(tool="query_evidence", results=results)


# ---------------------------------------------------------------------------
# recognize_molecules — read-only MolDet + MolParser pass over one page
# ---------------------------------------------------------------------------
class AgentRecognizeMoleculesRequest(BaseModel):
    """A page (optionally one region) of an imported document."""

    doc_id: str = Field(..., min_length=1, max_length=256)
    page: int = Field(..., ge=1)
    #: PDF points, bottom-left origin; keeps one table cell / figure.
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    max_molecules: int = Field(10, ge=1, le=20)


class AgentRecognizeMoleculesResponse(BaseModel):
    success: bool = True
    tool: Literal["recognize_molecules"] = "recognize_molecules"
    page: int
    page_width_pts: float
    page_height_pts: float
    dpi: float
    region: list[float] | None = None
    count: int = 0
    truncated: bool = False
    molecules: list[dict] = Field(default_factory=list)


@router.post(
    "/tools/recognize-molecules", response_model=AgentRecognizeMoleculesResponse
)
async def agent_recognize_molecules(
    body: AgentRecognizeMoleculesRequest,
) -> AgentRecognizeMoleculesResponse:
    """Recognize the structures drawn on one page of a library document."""

    from mbforge.service.use_cases.molecule.recognition import (
        recognize_page_molecules,
    )

    pdf_path = resolve_pdf_path(str(resolve_library_root(None)), body.doc_id)
    result = await asyncio.to_thread(
        recognize_page_molecules,
        str(pdf_path),
        page=body.page,
        region=body.region,
        max_molecules=body.max_molecules,
    )
    return AgentRecognizeMoleculesResponse(**result)


# ---------------------------------------------------------------------------
# library_sql — guarded read-only escape hatch
# ---------------------------------------------------------------------------
class AgentLibrarySqlRequest(BaseModel):
    """An empty ``sql`` returns the schema so the model can discover tables."""

    sql: str = Field("", max_length=4000)
    max_rows: int = Field(200, ge=1, le=1000)


class AgentLibrarySqlResponse(BaseModel):
    # ``success=False`` carries a guard/execution error the model can correct
    # from; transport failures stay real HTTP errors.
    success: bool = True
    tool: Literal["library_sql"] = "library_sql"
    tables: list[dict] | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str | None = None


@router.post("/tools/library-sql", response_model=AgentLibrarySqlResponse)
async def agent_library_sql(body: AgentLibrarySqlRequest) -> AgentLibrarySqlResponse:
    """Run a single guarded read-only SELECT against the library database."""

    root = str(resolve_library_root(None))
    if not body.sql.strip():
        tables = await asyncio.to_thread(library_schema, root)
        return AgentLibrarySqlResponse(tables=tables)
    try:
        result = await asyncio.to_thread(
            run_library_sql, root, body.sql, max_rows=body.max_rows
        )
    except ValidationError as exc:
        return AgentLibrarySqlResponse(success=False, error=exc.message)
    return AgentLibrarySqlResponse(**result)

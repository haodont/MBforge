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
    library-sql       guarded read-only SELECT escape hatch
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from mbforge.api.http._path_utils import resolve_library_root
from mbforge.domain.docking import DockingBox, DockingLigand
from mbforge.foundation.errors import ValidationError
from mbforge.service.dto.docking import DockingBoxModel, DockingLigandModel
from mbforge.service.use_cases.agent_queries import (
    library_schema,
    library_stats,
    query_activities,
    query_documents,
    query_evidence,
    run_library_sql,
)
from mbforge.service.use_cases.docking import jobs as docking_jobs
from mbforge.service.use_cases.docking import receptors as docking_receptors
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
    doc_id: str = Field(..., min_length=1, max_length=256)
    target: str = Field("", max_length=256)
    assay_description: str = Field("", max_length=256)
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


# ---------------------------------------------------------------------------
# Docking (agent-driven docking interface)
# ---------------------------------------------------------------------------
class AgentDockingListResponse(BaseModel):
    success: bool = True
    tool: str
    items: list[dict] = Field(default_factory=list)


class AgentDockingJobResponse(BaseModel):
    success: bool = True
    tool: str
    job: dict = Field(default_factory=dict)


@router.post("/tools/docking-receptors", response_model=AgentDockingListResponse)
async def agent_docking_receptors() -> AgentDockingListResponse:
    """List the prepared receptors available to dock against."""

    items = await asyncio.to_thread(
        docking_receptors.list_receptors, str(resolve_library_root(None))
    )
    return AgentDockingListResponse(tool="list_receptors", items=items)


class AgentDockingJobsRequest(BaseModel):
    status: str = Field("", max_length=32)
    limit: int = Field(20, ge=1, le=100)


@router.post("/tools/docking-jobs", response_model=AgentDockingListResponse)
async def agent_docking_jobs(
    body: AgentDockingJobsRequest,
) -> AgentDockingListResponse:
    """List recent docking jobs (optionally filtered by status)."""

    items = await asyncio.to_thread(
        docking_jobs.list_jobs,
        str(resolve_library_root(None)),
        status=body.status or None,
        limit=body.limit,
    )
    return AgentDockingListResponse(tool="list_docking_jobs", items=items)


class AgentDockingJobRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=128)


@router.post("/tools/docking-job", response_model=AgentDockingJobResponse)
async def agent_docking_job(body: AgentDockingJobRequest) -> AgentDockingJobResponse:
    """Fetch one docking job with its ranked poses."""

    job = await asyncio.to_thread(
        docking_jobs.get_job, str(resolve_library_root(None)), body.job_id
    )
    return AgentDockingJobResponse(tool="get_docking_job", job=job)


class AgentRunDockingRequest(BaseModel):
    """Explicit docking request: the agent must name receptor, ligands and box."""

    receptor_id: str = Field(..., min_length=1, max_length=128)
    ligands: list[DockingLigandModel] = Field(..., min_length=1, max_length=200)
    box: DockingBoxModel
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/tools/run-docking", response_model=AgentDockingJobResponse)
async def agent_run_docking(body: AgentRunDockingRequest) -> AgentDockingJobResponse:
    """Queue a docking job (returns a job_id to poll via get_docking_job)."""

    root = str(resolve_library_root(None))
    box = DockingBox(
        center=tuple(float(v) for v in body.box.center),  # type: ignore[arg-type]
        size=tuple(float(v) for v in body.box.size),  # type: ignore[arg-type]
    )
    ligands = [
        DockingLigand(
            label=item.label or item.mol_id or f"ligand-{index + 1}",
            smiles=item.smiles,
            mol_id=item.mol_id,
        )
        for index, item in enumerate(body.ligands)
        if item.smiles.strip()
    ]
    if not ligands:
        raise ValidationError("at least one ligand needs a SMILES")
    job = await asyncio.to_thread(
        docking_jobs.enqueue_job,
        root,
        receptor_id=body.receptor_id,
        ligands=ligands,
        box=box,
        params=body.params,
    )
    return AgentDockingJobResponse(tool="run_docking", job=job)

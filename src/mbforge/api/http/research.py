"""Research history and turns. Provider calls remain entirely in the Node sidecar."""

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.background import BackgroundTask

from mbforge.api.http._path_utils import resolve_library_root, resolve_pdf_path
from mbforge.api.http.agent import (
    AgentMoleculeSearchRequest,
    AgentQueryActivitiesRequest,
    AgentQueryDocumentsRequest,
    AgentQueryEvidenceRequest,
    AgentSearchLibraryRequest,
)
from mbforge.contracts.research import (
    ObjectId,
    ResearchArtifactReference,
    ResearchModel,
    ResearchRuntimeSpec,
    ResearchSession,
    ResearchSessionSummary,
    ResearchTurnRequest,
)
from mbforge.contracts.review_proposal import ReviewProposal
from mbforge.service.use_cases import agent_queries, research, review_proposals
from mbforge.service.use_cases.documents.patent_facts import load_patent_facts
from mbforge.service.use_cases.molecule.queries import search_molecules
from mbforge.service.use_cases.pipeline.ingest import list_tasks

router = APIRouter()


class CreateSessionRequest(ResearchModel):
    library_root: str | None = None
    title: str = Field(default="New research", min_length=1, max_length=160)


class ImportSessionRequest(ResearchModel):
    library_root: str | None = None
    session: ResearchSession


class ChatRequest(ResearchTurnRequest):
    library_root: str | None = None


class CredentialRequest(ResearchModel):
    credential: str = Field(min_length=20, max_length=128)


class ActivityStatsRequest(CredentialRequest):
    doc_id: str = Field(default="", max_length=128)


class ProposeReviewRequest(CredentialRequest):
    #: One bounded batch: a proposal is cheap to record but expensive to read.
    items: list[ReviewProposal] = Field(..., min_length=1, max_length=10)


class MoleculeQueryRequest(CredentialRequest):
    query: AgentMoleculeSearchRequest


class DocumentQueryRequest(CredentialRequest):
    query: AgentQueryDocumentsRequest


class LibraryQueryRequest(CredentialRequest):
    query: AgentSearchLibraryRequest


class EvidenceQueryRequest(CredentialRequest):
    query: AgentQueryEvidenceRequest


class RecognizeMoleculesRequest(CredentialRequest):
    """Read-only MolDet + MolParser pass over one page of a bound document."""

    doc_id: str = Field(..., min_length=1, max_length=256)
    page: int = Field(..., ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    max_molecules: int = Field(10, ge=1, le=20)


class ActivityQueryRequest(CredentialRequest):
    query: AgentQueryActivitiesRequest


class TaskQueryRequest(CredentialRequest):
    run_id: ObjectId | None = None


class FactsQueryRequest(CredentialRequest):
    doc_id: ObjectId


class StartAnalysisRequest(CredentialRequest):
    doc_ids: list[ObjectId] = Field(min_length=1, max_length=8)


@router.post("/sessions", response_model=ResearchSession)
async def create_session(body: CreateSessionRequest) -> ResearchSession:
    return await asyncio.to_thread(
        research.create_session,
        str(resolve_library_root(body.library_root)),
        body.title,
    )


@router.get("/sessions", response_model=list[ResearchSessionSummary])
async def list_sessions(
    library_root: str | None = None,
) -> list[ResearchSessionSummary]:
    return await asyncio.to_thread(
        research.list_sessions, str(resolve_library_root(library_root))
    )


@router.post("/sessions/import", response_model=ResearchSession)
async def import_session(body: ImportSessionRequest) -> ResearchSession:
    return await asyncio.to_thread(
        research.import_session,
        str(resolve_library_root(body.library_root)),
        body.session,
    )


@router.get("/sessions/{session_id}", response_model=ResearchSession)
async def get_session(
    session_id: ObjectId, library_root: str | None = None
) -> ResearchSession:
    return await asyncio.to_thread(
        research.get_session, str(resolve_library_root(library_root)), session_id
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: ObjectId, library_root: str | None = None
) -> dict[str, bool]:
    deleted = await asyncio.to_thread(
        research.delete_session, str(resolve_library_root(library_root)), session_id
    )
    return {"deleted": deleted}


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: ObjectId, body: ChatRequest) -> StreamingResponse:
    root = str(resolve_library_root(body.library_root))
    turn = await research.prepare_turn(
        root,
        session_id,
        ResearchTurnRequest.model_validate(body.model_dump(exclude={"library_root"})),
    )

    async def events():
        async for event in research.stream_turn(turn):
            yield f"event: {event.type}\ndata: {json.dumps(event.model_dump(exclude={'type'}), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(research.abandon_turn, turn),
    )


@router.post("/runtime/spec", response_model=ResearchRuntimeSpec)
async def runtime_spec(body: CredentialRequest) -> ResearchRuntimeSpec:
    return research.runtime_spec(body.credential)


@router.post("/runtime/library-stats")
async def library_stats(body: CredentialRequest):
    scope = research.resolve_scope(body.credential)
    return await asyncio.to_thread(agent_queries.library_stats, scope.library_root)


@router.post("/runtime/molecule-search")
async def molecule_search(body: MoleculeQueryRequest):
    scope = research.resolve_scope(body.credential)
    query = body.query
    return await asyncio.to_thread(
        search_molecules,
        scope.library_root,
        query.query,
        top_k=query.top_k,
        mode=query.mode,
        similarity_threshold=query.similarity_threshold,
    )


@router.post("/runtime/query-documents")
async def query_documents(body: DocumentQueryRequest):
    scope = research.resolve_scope(body.credential)
    return await asyncio.to_thread(
        agent_queries.query_documents, scope.library_root, **body.query.model_dump()
    )


@router.post("/runtime/search-library")
async def search_library(body: LibraryQueryRequest):
    scope = research.resolve_scope(body.credential)
    return await asyncio.to_thread(
        agent_queries.search_library, scope.library_root, **body.query.model_dump()
    )


@router.post("/runtime/query-evidence")
async def query_evidence(body: EvidenceQueryRequest):
    scope = research.resolve_scope(body.credential)
    return await asyncio.to_thread(
        agent_queries.query_evidence, scope.library_root, **body.query.model_dump()
    )


@router.post("/runtime/recognize-molecules")
async def recognize_molecules(body: RecognizeMoleculesRequest):
    """Recognize structures drawn on one page; nothing is persisted."""
    from mbforge.service.use_cases.molecule.recognition import (
        recognize_page_molecules,
    )

    scope = research.resolve_scope(body.credential)
    pdf_path = resolve_pdf_path(scope.library_root, body.doc_id)
    return await asyncio.to_thread(
        recognize_page_molecules,
        str(pdf_path),
        page=body.page,
        region=body.region,
        max_molecules=body.max_molecules,
    )


@router.post("/runtime/query-activities")
async def query_activities(body: ActivityQueryRequest):
    scope = research.resolve_scope(body.credential)
    return await asyncio.to_thread(
        agent_queries.query_activities, scope.library_root, **body.query.model_dump()
    )


@router.post("/runtime/activity-stats")
async def activity_stats(body: ActivityStatsRequest):
    """Coverage of printed readings (per library or per document)."""
    scope = research.resolve_scope(body.credential)
    return await asyncio.to_thread(
        agent_queries.activity_stats, scope.library_root, doc_id=body.doc_id
    )


@router.post("/runtime/query-tasks")
async def query_tasks(body: TaskQueryRequest):
    scope = research.resolve_scope(body.credential)
    tasks = await list_tasks(scope.library_root)
    return [
        {key: task[key] for key in ("id", "run_id", "doc_id", "stage", "status")}
        for task in tasks
        if body.run_id is None or task["run_id"] == body.run_id
    ]


@router.post("/runtime/patent-facts")
async def patent_facts(body: FactsQueryRequest):
    scope = research.resolve_scope(body.credential)
    facts = await asyncio.to_thread(load_patent_facts, scope.library_root, body.doc_id)
    if facts is None:
        return {"reference": None, "available": False}
    reference = (
        ResearchArtifactReference(
            doc_id=facts.doc_id, run_id=facts.run_id, revision=facts.revision
        )
        if facts.revision > 0
        else None
    )
    if reference:
        await research.record_artifact(body.credential, reference)
    return {
        "reference": reference,
        "available": True,
        "analysis_status": facts.analysis_status,
        "extraction_mode": facts.extraction_mode,
        "assay_methods": facts.assay_methods[:20],
        "measurements": facts.measurements[:50],
        "review_count": len(facts.review_candidates),
        "truncated": len(facts.assay_methods) > 20 or len(facts.measurements) > 50,
    }


@router.post("/runtime/propose-review")
async def propose_review(body: ProposeReviewRequest):
    """Record AI proposals; a human decision freezes the target."""
    scope = research.resolve_scope(body.credential)
    results = await asyncio.to_thread(
        review_proposals.propose_items, scope.library_root, body.items
    )
    return {"items": [result.model_dump() for result in results]}


@router.post("/runtime/start-patent-analysis")
async def start_patent_analysis(body: StartAnalysisRequest):
    references = await research.start_patent_analysis(body.credential, body.doc_ids)
    return {"references": references, "started_or_reused": bool(references)}

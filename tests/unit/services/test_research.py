"""New public contracts: replay does not run tools, stop persists, libraries isolate."""

from collections.abc import AsyncIterator

import pytest

from mbforge.contracts.research import (
    ResearchDelta,
    ResearchDone,
    ResearchEvent,
    ResearchTurnRequest,
)
from mbforge.db.sqlite.repositories import SqliteResearchRepository
from mbforge.foundation.errors import ConflictError, NotFoundError, ValidationError
from mbforge.foundation.layout import LibraryLayout
from mbforge.ports.repositories import get_repositories
from mbforge.server.ingest import queue, worker
from mbforge.server.research import InMemoryResearchRegistry
from mbforge.service.ports import research as research_ports
from mbforge.service.use_cases import research
from mbforge.service.use_cases.pipeline import ingest


class FakeRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def is_active(self, session_id: str) -> bool:
        return False

    async def stream(self, credential: str) -> AsyncIterator[ResearchEvent]:
        self.calls += 1
        yield ResearchDelta(text="Evidence-backed reply")
        yield ResearchDone(text="Evidence-backed reply")


@pytest.mark.asyncio
async def test_research_text_search_keeps_credential_library_after_active_library_switch(
    runtime,
    tmp_path,
    patch_config_root,
):
    """The new public search endpoint cannot escape or reuse an expired scope."""
    from fastapi.testclient import TestClient

    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.server.app import create_app

    client = TestClient(create_app())
    research_ports.configure_research_runtime(runtime, InMemoryResearchRegistry())
    root = str(tmp_path / "bound")
    other = str(tmp_path / "other")
    for library, doc_id in ((root, "bound-doc"), (other, "other-doc")):
        seed_document(library, doc_id)
        persist_source_evidence(
            library,
            [
                SourceEvidence.create(
                    doc_id=doc_id,
                    page=1,
                    bbox=(1, 2, 3, 4),
                    raw_text="MRGPRX2 IC50",
                )
            ],
        )
    session = research.create_session(root, "Research")
    prepared = await research.prepare_turn(
        root,
        session.id,
        ResearchTurnRequest(request_id="search-1", message="Find MRGPRX2"),
    )
    patch_config_root(other)
    body = {"credential": prepared.credential, "query": {"query": "MRGPRX2"}}
    response = client.post("/api/v1/research/runtime/search-library", json=body)
    assert response.status_code == 200
    assert [row["doc_id"] for row in response.json()["results"]] == ["bound-doc"]
    await research.abandon_turn(prepared)
    assert (
        client.post("/api/v1/research/runtime/search-library", json=body).status_code
        == 404
    )


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> FakeRuntime:
    runtime = FakeRuntime()
    monkeypatch.setattr(research_ports, "_runtime", runtime)
    monkeypatch.setattr(research_ports, "_registry", InMemoryResearchRegistry())
    monkeypatch.setattr(ingest, "ensure_worker", lambda _root: None)
    return runtime


@pytest.mark.asyncio
async def test_research_request_replay_preserves_history_without_rerunning(
    runtime, tmp_path
):
    root = str(tmp_path)
    session = research.create_session(root, "New research")
    request = ResearchTurnRequest(
        request_id="request-1", message="Explain the evidence"
    )
    prepared = await research.prepare_turn(root, session.id, request)
    original = [event async for event in research.stream_turn(prepared)]
    replay = await research.prepare_turn(root, session.id, request)
    repeated = [event async for event in research.stream_turn(replay)]
    assert repeated[-1] == original[-1]
    assert runtime.calls == 1
    restored = research.get_session(root, session.id)
    assert len(restored.messages) == 2
    assert restored.messages[-1].content == "Evidence-backed reply"
    assert restored.messages[-1].status == "complete"
    with pytest.raises(ConflictError):
        await research.prepare_turn(
            root,
            session.id,
            request.model_copy(update={"message": "A different action"}),
        )
    assert research.get_session(root, session.id) == restored


@pytest.mark.asyncio
async def test_research_stop_keeps_partial_reply_and_restart_recovers_orphan(
    runtime, tmp_path, monkeypatch
):
    """A stopped turn keeps its partial reply and revokes the tool credential;
    a restarted process recovers the orphaned reply only in its own library."""
    root = str(tmp_path / "library-a")

    orphan = research.create_session(root, "Orphan research")
    await research.prepare_turn(
        root,
        orphan.id,
        ResearchTurnRequest(request_id="orphan-1", message="Explain"),
    )
    monkeypatch.setattr(research_ports, "_registry", InMemoryResearchRegistry())
    assert research.get_session(root, orphan.id).messages[-1].status == "stopped"
    with pytest.raises(NotFoundError):
        research.get_session(str(tmp_path / "library-b"), orphan.id)
    # Recovery must not re-run the runtime.
    assert runtime.calls == 0

    session = research.create_session(root, "New research")
    prepared = await research.prepare_turn(
        root, session.id, ResearchTurnRequest(request_id="request-1", message="Explain")
    )
    stream = research.stream_turn(prepared)
    assert (await anext(stream)).type == "delta"
    await stream.aclose()
    restored = research.get_session(root, session.id)
    assert restored.messages[-1].content == "Evidence-backed reply"
    assert restored.messages[-1].status == "stopped"
    assert research_ports.get_research_registry().resolve(prepared.credential) is None


def seed_document(root: str, doc_id: str) -> None:
    filename = f"{doc_id}.pdf"
    get_repositories(root).documents.insert(
        {
            "doc_id": doc_id,
            "file_name": filename,
            "title": doc_id,
            "page_count": 1,
            "status": "pending",
            "created_at": "2026-10-13 00:00:00",
        }
    )
    path = LibraryLayout(root).storage_dir(doc_id) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-test-source")


@pytest.mark.asyncio
async def test_research_analysis_retry_reuses_queue_after_reference_save_failure(
    runtime, tmp_path, monkeypatch
):
    root = str(tmp_path)
    seed_document(root, "selected-doc")
    session = research.create_session(root, "New research")
    request = ResearchTurnRequest(
        request_id="request-1",
        message="Analyze selected patents",
        context={"document_ids": ["selected-doc"], "allow_patent_analysis": True},
    )
    prepared = await research.prepare_turn(root, session.id, request)
    save = SqliteResearchRepository.save
    fail_once = True

    def interrupted_save(self, snapshot, expected_revision):
        nonlocal fail_once
        if fail_once and snapshot.messages[-1].task_refs:
            fail_once = False
            raise OSError("simulated response persistence failure")
        save(self, snapshot, expected_revision)

    monkeypatch.setattr(SqliteResearchRepository, "save", interrupted_save)
    with pytest.raises(OSError):
        await research.start_patent_analysis(prepared.credential, ["selected-doc"])
    first_run = queue.run_ids_for_doc(root, "selected-doc")
    restored = await research.start_patent_analysis(
        prepared.credential, ["selected-doc"]
    )
    assert len(restored) == 3
    assert queue.run_ids_for_doc(root, "selected-doc") == first_run
    assert {reference.run_id for reference in restored} == set(first_run)
    assert research.get_session(root, session.id).messages[-1].task_refs == restored


@pytest.mark.asyncio
async def test_research_analysis_attaches_after_active_preparation_without_early_finalization(
    runtime, tmp_path
):
    root = str(tmp_path)
    seed_document(root, "selected-doc")
    import_run = await ingest.enqueue(root, "selected-doc")
    session = research.create_session(root, "New research")
    prepared = await research.prepare_turn(
        root,
        session.id,
        ResearchTurnRequest(
            request_id="request-1",
            message="Analyze",
            context={"document_ids": ["selected-doc"], "allow_patent_analysis": True},
        ),
    )
    references = await research.start_patent_analysis(
        prepared.credential, ["selected-doc"]
    )
    assert {reference.run_id for reference in references} == {import_run}
    tasks = queue.list_tasks(root)
    patent = next(task for task in tasks if task["stage"] == "patent")
    assert patent["status"] == "blocked"
    extract = worker._claim_rows(root, "research-test-worker", 1)[0]
    assert extract["stage"] == "extract"
    assert queue.set_node_status(root, extract["id"], "done")
    queue.advance_dependents(
        root, doc_id="selected-doc", run_id=import_run, completed_stage="extract"
    )
    markdown = worker._claim_rows(root, "research-test-worker", 1)[0]
    assert markdown["stage"] == "markdown"
    assert queue.set_node_status(root, markdown["id"], "done")
    assert not queue.claim_finalize(root, doc_id="selected-doc", run_id=import_run)
    queue.advance_dependents(
        root, doc_id="selected-doc", run_id=import_run, completed_stage="markdown"
    )
    assert (
        next(task for task in queue.list_tasks(root) if task["stage"] == "patent")[
            "status"
        ]
        == "pending"
    )
    claimed = worker._claim_rows(root, "research-test-worker", 1)[0]
    assert claimed["id"] == patent["id"]
    assert queue.set_node_status(root, patent["id"], "done")
    assert queue.claim_finalize(root, doc_id="selected-doc", run_id=import_run)
    assert not queue.claim_finalize(root, doc_id="selected-doc", run_id=import_run)


@pytest.mark.asyncio
async def test_research_analysis_enforces_authorization_and_selected_scope(
    runtime, tmp_path, patch_config_root
):
    """Patent analysis is refused when it is not authorized or when it asks
    for a document outside the session's selected scope."""
    cases = [(False, "selected-doc"), (True, "other-doc")]
    for index, (authorized, requested_doc) in enumerate(cases):
        root = str(tmp_path / f"library-a-{index}")
        other_root = str(tmp_path / f"library-b-{index}")
        seed_document(root, "selected-doc")
        seed_document(other_root, "other-doc")
        session = research.create_session(root, "New research")
        prepared = await research.prepare_turn(
            root,
            session.id,
            ResearchTurnRequest(
                request_id="request-1",
                message="Analyze",
                context={
                    "document_ids": ["selected-doc"],
                    "allow_patent_analysis": authorized,
                },
            ),
        )
        patch_config_root(other_root)
        with pytest.raises(ValidationError):
            await research.start_patent_analysis(prepared.credential, [requested_doc])
        assert queue.list_tasks(root) == [], f"{authorized!r} {requested_doc!r}"
        assert queue.list_tasks(other_root) == [], f"{authorized!r} {requested_doc!r}"
        if authorized:
            references = await research.start_patent_analysis(
                prepared.credential, ["selected-doc"]
            )
            assert references and all(
                reference.doc_id == "selected-doc" for reference in references
            )
            assert queue.list_tasks(other_root) == []


@pytest.mark.asyncio
async def test_research_delete_removes_conversation_files_but_keeps_background_tasks(
    runtime, tmp_path
):
    root = str(tmp_path)
    seed_document(root, "selected-doc")
    session = research.create_session(root, "New research")
    prepared = await research.prepare_turn(
        root,
        session.id,
        ResearchTurnRequest(
            request_id="request-1",
            message="Analyze",
            context={"document_ids": ["selected-doc"], "allow_patent_analysis": True},
        ),
    )
    await research.start_patent_analysis(prepared.credential, ["selected-doc"])
    _ = [event async for event in research.stream_turn(prepared)]
    tasks = queue.list_tasks(root)
    path = LibraryLayout(root).research_session_file(session.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("private conversation", encoding="utf-8")
    assert research.delete_session(root, session.id)
    assert not path.exists()
    assert queue.list_tasks(root) == tasks
    with pytest.raises(NotFoundError):
        research.get_session(root, session.id)

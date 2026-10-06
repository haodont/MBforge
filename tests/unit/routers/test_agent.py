from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.api.http import agent
from mbforge.server.app import create_app


def test_agent_molecule_tool_resolves_library_server_side(monkeypatch) -> None:
    """The public tool contract must not let the model choose a library path."""

    captured: dict[str, object] = {}

    monkeypatch.setattr(agent, "resolve_library_root", lambda _: "C:/library")

    def fake_search(root: str, query: str, **kwargs):
        captured.update(root=root, query=query, kwargs=kwargs)
        return [{"mol_id": "M-1", "canonical_smiles": "CCO"}]

    monkeypatch.setattr(agent, "search_molecules", fake_search)

    response = TestClient(create_app()).post(
        "/api/v1/agent/tools/molecule-search",
        json={"query": "ethanol", "top_k": 1},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [{"mol_id": "M-1", "canonical_smiles": "CCO"}]
    assert captured == {
        "root": "C:/library",
        "query": "ethanol",
        "kwargs": {
            "top_k": 1,
            "mode": "auto",
            "similarity_threshold": 0.5,
        },
    }


def _seed_document(library: Path) -> None:
    from mbforge.db import document_records
    from mbforge.db.sqlite.database import DatabaseManager

    DatabaseManager.get(str(library)).initialize()
    document_records.insert(
        str(library),
        {
            "doc_id": "doc-1",
            "file_name": "doc-1.pdf",
            "title": "Seed",
            "page_count": 1,
            "created_at": "2026-01-01 00:00:00",
        },
    )


def test_agent_query_documents_forwards_filters(monkeypatch) -> None:
    """The structured query tool resolves the library server-side and forwards filters."""

    captured: dict[str, object] = {}

    monkeypatch.setattr(agent, "resolve_library_root", lambda _: "C:/library")

    def fake_query(root: str, **kwargs):
        captured.update(root=root, kwargs=kwargs)
        return [{"doc_id": "doc-1"}]

    monkeypatch.setattr(agent, "query_documents", fake_query)

    response = TestClient(create_app()).post(
        "/api/v1/agent/tools/query-documents",
        json={"status": "ready", "name": "aspirin", "limit": 5},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [{"doc_id": "doc-1"}]
    assert captured == {
        "root": "C:/library",
        "kwargs": {"status": "ready", "name": "aspirin", "limit": 5},
    }


def test_agent_library_stats_counts_seeded_rows(
    app_client: TestClient, tmp_library: Path
) -> None:
    _seed_document(tmp_library)

    response = app_client.post("/api/v1/agent/tools/library-stats", json={})

    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["documents"]["total"] == 1
    assert stats["documents"]["by_status"] == {"pending": 1}


def test_agent_library_sql_reads_and_refuses_writes(
    app_client: TestClient, tmp_library: Path
) -> None:
    """library_sql runs a read-only SELECT and refuses writes / multi-statements."""
    _seed_document(tmp_library)

    # Empty sql returns the schema so the model can discover tables.
    schema = app_client.post("/api/v1/agent/tools/library-sql", json={"sql": ""}).json()
    assert any(table["table"] == "documents" for table in schema["tables"])

    ok = app_client.post(
        "/api/v1/agent/tools/library-sql",
        json={"sql": "SELECT doc_id FROM documents"},
    ).json()
    assert ok["success"] is True
    assert ok["columns"] == ["doc_id"]
    assert ok["rows"] == [["doc-1"]]

    for bad in (
        "DELETE FROM documents",
        "SELECT 1; DROP TABLE documents",
        "PRAGMA table_info(documents)",
    ):
        refused = app_client.post(
            "/api/v1/agent/tools/library-sql", json={"sql": bad}
        ).json()
        assert refused["success"] is False
        assert refused["error"]

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


def _seed_document(library: Path, doc_id: str = "doc-1") -> None:
    from mbforge.db import document_records
    from mbforge.db.sqlite.database import DatabaseManager

    DatabaseManager.get(str(library)).initialize()
    document_records.insert(
        str(library),
        {
            "doc_id": doc_id,
            "file_name": f"{doc_id}.pdf",
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


def test_agent_search_library_returns_literal_bounded_evidence_and_pagination(
    app_client: TestClient,
    tmp_library: Path,
) -> None:
    """Public search covers SQL text with literal terms, provenance and safe limits."""
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence

    _seed_document(tmp_library)
    _seed_document(tmp_library, "doc-2")
    rows = [
        SourceEvidence.create(
            doc_id="doc-1",
            page=page,
            bbox=(1, 2, 3, 4),
            raw_text="x" * 2500 + " MRGPRX2 IC50 10 nM 100% " + "x" * 2500,
        )
        for page in (1, 2)
    ]
    persist_source_evidence(tmp_library, rows)
    persist_source_evidence(
        tmp_library,
        [
            SourceEvidence.create(
                doc_id="doc-2",
                page=1,
                bbox=(1, 2, 3, 4),
                raw_text="MRGPRX2 review",
            )
        ],
    )
    response = app_client.post(
        "/api/v1/agent/tools/search-library", json={"query": "mrgprx2 ic50", "limit": 1}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["has_more"] and payload["next_offset"] == 1
    item = payload["results"][0]
    assert item["evidence_id"] == rows[0].evidence_id
    assert item["doc_id"] == "doc-1" and item["page"] == 1
    assert "MRGPRX2 IC50" in item["snippet"]
    assert len(item["snippet"]) == 2000 and item["truncated"]
    second = app_client.post(
        "/api/v1/agent/tools/search-library",
        json={"query": "MRGPRX2 IC50", "limit": 1, "offset": 1},
    ).json()
    assert second["results"][0]["page"] == 2 and not second["has_more"]
    literal = app_client.post(
        "/api/v1/agent/tools/search-library", json={"query": "%"}
    ).json()
    assert len(literal["results"]) == 2
    no_wildcard = app_client.post(
        "/api/v1/agent/tools/search-library", json={"query": "_"}
    ).json()
    assert no_wildcard["results"] == []
    scoped = app_client.post(
        "/api/v1/agent/tools/search-library",
        json={"query": "MRGPRX2", "doc_id": "other-doc"},
    ).json()
    assert scoped["results"] == []
    across = app_client.post(
        "/api/v1/agent/tools/search-library", json={"query": "MRGPRX2"}
    ).json()
    assert {row["doc_id"] for row in across["results"]} == {"doc-1", "doc-2"}
    for body in (
        {"query": " "},
        {"query": "x", "limit": 51},
        {"query": "x", "library_root": "other-library"},
    ):
        assert (
            app_client.post("/api/v1/agent/tools/search-library", json=body).status_code
            == 422
        )


def test_agent_library_sql_reads_and_refuses_writes(
    app_client: TestClient, tmp_library: Path
) -> None:
    """library_sql runs a read-only SELECT and refuses writes / multi-statements."""
    _seed_document(tmp_library)

    # Empty sql returns the schema so the model can discover tables.
    schema = app_client.post("/api/v1/agent/tools/library-sql", json={"sql": ""}).json()
    assert any(table["table"] == "documents" for table in schema["tables"])
    assert all(not table["table"].startswith("research_") for table in schema["tables"])

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
        "SELECT payload FROM research_sessions",
    ):
        refused = app_client.post(
            "/api/v1/agent/tools/library-sql", json={"sql": bad}
        ).json()
        assert refused["success"] is False
        assert refused["error"]


def test_agent_recognize_molecules_tool_resolves_pdf_and_forwards_region(
    monkeypatch,
) -> None:
    """The recognizer tool resolves the PDF server-side and forwards the region."""

    captured: dict[str, object] = {}

    monkeypatch.setattr(agent, "resolve_library_root", lambda _: "C:/library")
    monkeypatch.setattr(
        agent, "resolve_pdf_path", lambda root, doc_id: Path(f"{root}/{doc_id}.pdf")
    )

    from mbforge.service.use_cases.molecule import recognition

    def fake_recognize(pdf_path: str, **kwargs):
        captured.update(pdf_path=pdf_path, kwargs=kwargs)
        return {
            "page": kwargs["page"],
            "page_width_pts": 612.0,
            "page_height_pts": 792.0,
            "dpi": 200.0,
            "region": kwargs["region"],
            "count": 1,
            "truncated": False,
            "molecules": [{"index": 0, "smiles": "CCO", "labels": ["22A"]}],
        }

    monkeypatch.setattr(recognition, "recognize_page_molecules", fake_recognize)

    response = TestClient(create_app()).post(
        "/api/v1/agent/tools/recognize-molecules",
        json={
            "doc_id": "doc-1",
            "page": 3,
            "region": [0, 0, 306, 792],
            "max_molecules": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool"] == "recognize_molecules"
    assert body["count"] == 1
    assert body["molecules"][0]["smiles"] == "CCO"
    assert Path(captured["pdf_path"]) == Path("C:/library/doc-1.pdf")
    assert captured["kwargs"] == {
        "page": 3,
        "region": [0, 0, 306, 792],
        "max_molecules": 5,
    }

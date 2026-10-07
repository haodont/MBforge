from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _assert_error(response, expected_status: int, expected_error_code: str) -> dict:
    assert response.status_code == expected_status, response.text
    data = response.json()
    assert data["success"] is False
    assert data["error_code"] == expected_error_code
    return data


def test_documents_list_uses_configured_root(
    app_client: TestClient, tmp_library: Path
) -> None:
    # Import a document using the configured library root.
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        data={"title": "Test Paper"},
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["document"]["doc_id"]

    # A freshly imported document is visible immediately, resting at ``pending``.
    resp = app_client.post("/api/v1/documents/list", json={})
    assert resp.status_code == 200
    listed = {d["doc_id"]: d for d in resp.json()["documents"]}
    assert listed[doc_id]["status"] == "pending"

    from mbforge.service.use_cases.documents.library import LibraryStore

    LibraryStore.get(str(tmp_library)).update_document_status(doc_id, "ready")

    # List without explicit library_root falls back to global config (tmp_library).
    resp = app_client.post("/api/v1/documents/list", json={})
    assert resp.status_code == 200
    ids = {d["doc_id"] for d in resp.json()["documents"]}
    assert doc_id in ids


def test_documents_reingest_unknown_doc_returns_404(app_client: TestClient) -> None:
    # No explicit library_root; falls back to the configured temp library.
    _assert_error(
        app_client.post(
            "/api/v1/documents/reingest",
            json={"doc_id": "no-such-doc"},
        ),
        404,
        "not_found",
    )


def test_documents_patent_analysis_queues_patent_only_run(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Batch Patent analysis skips un-extracted docs and queues a Patent-only run otherwise."""
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.server.ingest import queue

    # Unknown / not-yet-extracted documents are skipped, not failed.
    resp = app_client.post(
        "/api/v1/documents/patent-analysis",
        json={"doc_ids": ["missing-doc"]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "enqueued": 0, "skipped": 1}

    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        data={"title": "Patent Paper"},
        files={"file": ("patent.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["document"]["doc_id"]

    # Import auto-enqueues Extract + Markdown; mark that run finished so the
    # document rests 'extracted' — the state Patent analysis is triggered from.
    from mbforge.db.sqlite.database import DatabaseManager

    db = DatabaseManager.get(str(tmp_library))
    with db.kb_conn() as conn:
        conn.execute(
            "UPDATE ingest_queue SET status = 'done' WHERE doc_id = ?", (doc_id,)
        )

    # Extract has produced evidence for this document, so it becomes eligible.
    persist_source_evidence(
        tmp_library,
        [
            SourceEvidence.create(
                doc_id=doc_id, page=1, bbox=(1, 1, 2, 2), raw_text="compound 1"
            )
        ],
    )

    resp = app_client.post(
        "/api/v1/documents/patent-analysis",
        json={"doc_ids": [doc_id]},
    )
    assert resp.status_code == 200
    assert resp.json()["enqueued"] == 1
    assert resp.json()["skipped"] == 0

    # The document's queued run is Patent-only.
    stages = {
        task["stage"]
        for task in queue.list_tasks(str(tmp_library))
        if task["doc_id"] == doc_id
    }
    assert stages == {"patent"}


def test_documents_delete_and_list_roundtrip(
    app_client: TestClient, tmp_library: Path
) -> None:
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        data={"title": "Test Paper"},
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["document"]["doc_id"]

    # Make the document visible first, so "gone from the list" is a real
    # assertion rather than a consequence of the processing filter.
    from mbforge.service.use_cases.documents.library import LibraryStore

    LibraryStore.get(str(tmp_library)).update_document_status(doc_id, "ready")
    resp = app_client.post("/api/v1/documents/list", json={})
    assert doc_id in {d["doc_id"] for d in resp.json()["documents"]}

    resp = app_client.post(
        "/api/v1/documents/delete",
        json={"doc_ids": [doc_id]},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = app_client.post("/api/v1/documents/list", json={})
    ids = {d["doc_id"] for d in resp.json()["documents"]}
    assert doc_id not in ids

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

    resp = app_client.post(
        "/api/v1/documents/delete",
        json={"doc_id": doc_id},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = app_client.post("/api/v1/documents/list", json={})
    ids = {d["doc_id"] for d in resp.json()["documents"]}
    assert doc_id not in ids

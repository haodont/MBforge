"""HTTP contract tests for capability auth and discovery."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_manifest_lists_read_and_write_capabilities(app_client: TestClient) -> None:
    response = app_client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    names = {item["name"] for item in body["capabilities"]}
    assert {"resolve_document", "submit_extraction"} <= names
    assert Path(body["token_path"]).parts[-2:] == (".mbforge", "capability-token")


def test_guide_creates_token_file(
    app_client: TestClient, tmp_library: Path
) -> None:
    response = app_client.get("/api/v1/capabilities/guide")
    assert response.status_code == 200
    assert "submit_extraction" in response.text
    assert (tmp_library / ".mbforge" / "capability-token").is_file()


def test_write_capability_requires_edit_token(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/v1/capabilities/submit_extraction",
        json={"doc_id": "missing"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "capability_forbidden"


def test_valid_token_reaches_business_validation(
    app_client: TestClient, tmp_library: Path
) -> None:
    app_client.get("/api/v1/capabilities/guide")
    token = (
        tmp_library / ".mbforge" / "capability-token"
    ).read_text(encoding="utf-8").strip()
    response = app_client.post(
        "/api/v1/capabilities/submit_extraction",
        json={"doc_id": "missing"},
        headers={"x-mbforge-token": token},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_unknown_capability_returns_404(app_client: TestClient) -> None:
    response = app_client.post("/api/v1/capabilities/not_a_capability", json={})
    assert response.status_code == 404

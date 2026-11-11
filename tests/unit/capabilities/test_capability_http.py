"""HTTP contract tests for capability auth and discovery."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_manifest_lists_read_and_write_capabilities(app_client: TestClient) -> None:
    response = app_client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    names = {item["name"] for item in body["capabilities"]}
    assert {
        "resolve_document",
        "submit_extraction",
        "submit_patent_analysis",
        "search_evidence",
        "ocr_page_region",
        "inspect_visual",
        "query_activities",
        "propose_review",
        "list_review_queue",
        "get_vocabulary",
    } <= names
    assert Path(body["token_path"]).parts[-2:] == (".mbforge", "capability-token")


def test_guide_creates_token_file(app_client: TestClient, tmp_library: Path) -> None:
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
        (tmp_library / ".mbforge" / "capability-token")
        .read_text(encoding="utf-8")
        .strip()
    )
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


def test_search_evidence_returns_an_empty_page(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/v1/capabilities/search_evidence",
        json={"query": "IC50", "limit": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"] == []
    assert body["truncated"] is False
    assert body["next_offset"] is None


def test_inspect_visual_page_molecules_reports_a_missing_document(
    app_client: TestClient,
) -> None:
    response = app_client.post(
        "/api/v1/capabilities/inspect_visual",
        json={"action": "page_molecules", "doc_id": "missing", "page": 1},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_ocr_page_region_reports_a_missing_document(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/v1/capabilities/ocr_page_region",
        json={"doc_id": "missing", "page": 1},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_inspect_visual_page_image_reports_a_missing_document(
    app_client: TestClient,
) -> None:
    response = app_client.post(
        "/api/v1/capabilities/inspect_visual",
        json={"action": "page_image", "doc_id": "missing", "page": 1},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_inspect_visual_rejects_invalid_base64(
    app_client: TestClient,
) -> None:
    response = app_client.post(
        "/api/v1/capabilities/inspect_visual",
        json={"action": "recognize_structure", "image_base64": "not base64"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"


def test_inspect_visual_maps_recognizer_output(
    app_client: TestClient, monkeypatch
) -> None:
    import base64
    import io
    from types import SimpleNamespace

    from PIL import Image

    from mbforge.service.pipeline.detection import recognition

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
    payload = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()

    def fake_recognize(_image):
        return SimpleNamespace(
            smiles="CCO", esmiles="CCO<sep>", coref=["7"], coref_primary="7"
        )

    monkeypatch.setattr(recognition, "recognize_molecule", fake_recognize)
    response = app_client.post(
        "/api/v1/capabilities/inspect_visual",
        json={"action": "recognize_structure", "image_base64": payload},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["smiles"] == "CCO"
    assert data["esmiles"] == "CCO<sep>"
    assert data["coref"] == ["7"] and data["recognized"] is True


def test_verify_structures_reports_a_missing_document(
    app_client: TestClient,
) -> None:
    response = app_client.post(
        "/api/v1/capabilities/verify_structures",
        json={"doc_id": "missing"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_verify_structures_returns_one_row_per_structure(
    app_client: TestClient, tmp_library: Path
) -> None:
    """The capability answers the structure/printed-mass check end to end."""
    import json

    from mbforge.db.document_records import insert as insert_document
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence

    doc_id = "doc-verify-cap"
    insert_document(
        tmp_library,
        {
            "doc_id": doc_id,
            "file_name": "doc-verify-cap.pdf",
            "title": "doc-verify-cap",
            "page_count": 1,
            "status": "extracted",
            "created_at": "2026-01-01 00:00:00",
        },
    )
    persist_source_evidence(
        tmp_library,
        [
            SourceEvidence.create(
                doc_id=doc_id,
                page=1,
                bbox=(10.0, 10.0, 20.0, 20.0),
                kind="molecule",
                raw_text=json.dumps(
                    {
                        "smiles": "Cn1cc2c(N[C@H]3CC[C@@H](N)CC3)nccc2n1",
                        "esmiles": "Cn1cc2c(N[C@H]3CC[C@@H](N)CC3)nccc2n1",
                        "moldet_conf": 0.94,
                        "properties": {"ocr_labels": ["化合物4"]},
                    },
                    ensure_ascii=False,
                ),
            ),
            SourceEvidence.create(
                doc_id=doc_id,
                page=1,
                bbox=(60.0, 700.0, 533.0, 720.0),
                kind="text",
                raw_text="[0327] 化合物4: LC-MS,M/Z(ESI):246.17[M+H]+",
            ),
        ],
    )

    response = app_client.post(
        "/api/v1/capabilities/verify_structures",
        json={"doc_id": doc_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["summary"]["structures"] == 1
    item = body["data"]["items"][0]
    assert item["formula"] == "C13H19N5"
    assert item["exact_mass"] == 245.164
    assert item["mass_check"] == "match"
    assert item["printed_ms"][0]["verdict"] == "match"
    assert body["truncated"] is False


def test_submit_patent_analysis_requires_edit_token(
    app_client: TestClient, tmp_library: Path
) -> None:
    app_client.get("/api/v1/capabilities/guide")
    token = (
        (tmp_library / ".mbforge" / "capability-token")
        .read_text(encoding="utf-8")
        .strip()
    )
    response = app_client.post(
        "/api/v1/capabilities/submit_patent_analysis",
        json={"doc_id": "missing"},
        headers={"x-mbforge-token": token},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_review_queue_lists_pending_decisions_with_their_review_center_ids(
    app_client: TestClient, tmp_library: Path
) -> None:
    """The capability keeps the kind + item_id pair the review-center route
    addresses, so an agent can link a decision instead of describing it."""
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.service.ports import get_repositories

    DatabaseManager.get(str(tmp_library)).initialize()
    get_repositories(str(tmp_library)).review.insert_review_item(
        item_id="unbound-1",
        kind="designation_unbound",
        doc_id="a" * 64,
        page=62,
        bbox=(10.0, 20.0, 30.0, 40.0),
        name="A-2",
        confidence=0.87,
        reasons=["printings disagree"],
        payload={"measurement_id": "m-1"},
    )

    response = app_client.post("/api/v1/capabilities/list_review_queue", json={})
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert body["truncated"] is False
    assert body["next_offset"] is None
    assert data["total"] == 1
    assert data["pending"] == 1
    assert data["stats"] == [
        {"kind": "designation_unbound", "status": "pending", "count": 1}
    ]
    item = data["items"][0]
    assert (item["kind"], item["item_id"]) == ("designation_unbound", "unbound-1")
    assert (item["doc_id"], item["short_id"]) == ("a" * 64, "a" * 12)
    assert (item["page"], item["status"]) == (62, "pending")
    assert item["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert (item["name"], item["confidence"]) == ("A-2", 0.87)
    assert item["reasons"] == ["printings disagree"]


def test_review_queue_rejects_an_unknown_kind(app_client: TestClient) -> None:
    """A misspelled kind must not read as "nothing pending"."""
    response = app_client.post(
        "/api/v1/capabilities/list_review_queue",
        json={"kind": "not_a_kind"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"
    assert response.json()["detail"] == "not_a_kind"

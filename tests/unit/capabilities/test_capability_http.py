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
        "document_read",
        "runs",
        "run_control",
        "inspect_visual",
        "query_activities",
        "propose_review",
        "list_review_queue",
        "get_vocabulary",
        "library_briefing",
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


def test_inspect_visual_page_text_reports_a_missing_document(
    app_client: TestClient,
) -> None:
    response = app_client.post(
        "/api/v1/capabilities/inspect_visual",
        json={"action": "page_text", "doc_id": "missing", "page": 1},
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


def test_get_binding_candidates_joins_readings_to_structures(
    app_client: TestClient, tmp_library: Path
) -> None:
    """The capability answers the binding package end to end.

    A reading names ``化合物4`` and the drawing prints it, so the designation
    reaches the structure that claims it, with the evidence to check the link.
    """
    import json

    from mbforge.contracts.measurement import MeasurementRecord
    from mbforge.db.document_records import insert as insert_document
    from mbforge.db.measurement_store import replace_document_measurements
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence

    doc_id = "doc-bind-cap"
    insert_document(
        tmp_library,
        {
            "doc_id": doc_id,
            "file_name": "doc-bind-cap.pdf",
            "title": "doc-bind-cap",
            "page_count": 1,
            "status": "extracted",
            "created_at": "2026-01-01 00:00:00",
        },
    )
    smiles = "Cn1cc2c(N[C@H]3CC[C@@H](N)CC3)nccc2n1"
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
                        "smiles": smiles,
                        "esmiles": smiles,
                        "moldet_conf": 0.94,
                        "name": "化合物4",
                        "properties": {"label_source": "crop"},
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
    )
    replace_document_measurements(
        tmp_library,
        doc_id,
        [
            MeasurementRecord(
                measurement_id="m-4",
                doc_id=doc_id,
                metric="IC50",
                activity_type="IC50",
                original_value=12.0,
                original_unit="nM",
                canonical_value=12.0,
                canonical_unit="nM",
                operator="=",
                reference_raw="化合物4",
                reference_key="4",
                reference_type="compound",
                page_num=1,
                evidence_ids=["ev-1"],
            ),
        ],
    )

    response = app_client.post(
        "/api/v1/capabilities/get_binding_candidates",
        json={"doc_id": doc_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["summary"]["readings"] == 1
    assert body["data"]["summary"]["designations"] == 1
    assert body["data"]["summary"]["candidate_structures"] == 1
    designation = body["data"]["designations"][0]
    assert designation["label_key"] == "4"
    assert designation["reading_ids"] == ["m-4"]
    candidate = designation["candidates"][0]
    assert candidate["label_keys"] == ["4"]
    assert candidate["label_sources"] == ["crop"]
    assert candidate["formula"] == "C13H19N5"


def test_analyze_series_joins_molecules_to_attributed_readings(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A SAR series carries each molecule's own readings, evidence and review.

    The join is the contract: an accepted reading reaches its molecule, a
    rejected link and an unattributed reading never leak in, and the molecule,
    reading and link review states all ride along so SAR is judged on settled
    data.
    """
    from mbforge.contracts.measurement import (
        MeasurementAttribution,
        MeasurementRecord,
    )
    from mbforge.db.document_records import insert as insert_document
    from mbforge.db.measurement_store import replace_document_measurements
    from mbforge.db.sqlite.database import DatabaseManager

    doc_id = "doc-sar-cap"
    insert_document(
        tmp_library,
        {
            "doc_id": doc_id,
            "file_name": "doc-sar-cap.pdf",
            "title": "doc-sar-cap",
            "page_count": 1,
            "status": "extracted",
            "created_at": "2026-01-01 00:00:00",
        },
    )
    db = DatabaseManager.get(str(tmp_library))
    db.initialize()
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO molecules (
                mol_id, smiles, esmiles, name, source_doc, source_type,
                status, canonical_smiles, review_status, properties
            ) VALUES
                ('CCO', 'CCO', 'CCO', 'compound-A', 'doc-sar-cap', 'image',
                 'active', 'CCO', 'confirmed', '{"structure_role": "complete"}'),
                ('CCN', 'CCN', 'CCN', 'compound-B', 'doc-sar-cap', 'image',
                 'active', 'CCN', 'pending', '{"structure_role": "complete"}')
            """
        )
    replace_document_measurements(
        tmp_library,
        doc_id,
        [
            MeasurementRecord(
                measurement_id="m1",
                doc_id=doc_id,
                metric="IC50",
                target="EGFR",
                canonical_value=12.0,
                canonical_unit="nM",
                original_value=12.0,
                original_unit="nM",
                page_num=2,
                evidence_ids=["ev-1"],
                review_status="accepted",
            ),
            MeasurementRecord(
                measurement_id="m2",
                doc_id=doc_id,
                metric="IC50",
                target="EGFR",
                canonical_value=80.0,
                canonical_unit="nM",
                page_num=3,
                evidence_ids=["ev-2"],
            ),
            MeasurementRecord(
                measurement_id="m3-orphan",
                doc_id=doc_id,
                metric="IC50",
                canonical_value=99.0,
                canonical_unit="nM",
                page_num=4,
            ),
            MeasurementRecord(
                measurement_id="m4-rejected",
                doc_id=doc_id,
                metric="IC50",
                canonical_value=5.0,
                canonical_unit="nM",
                page_num=5,
            ),
        ],
        [
            MeasurementAttribution(
                attribution_id="a1",
                measurement_id="m1",
                mol_id="CCO",
                doc_id=doc_id,
                method="rule",
                review_status="accepted",
                evidence_id="ev-1",
            ),
            MeasurementAttribution(
                attribution_id="a2",
                measurement_id="m2",
                mol_id="CCN",
                doc_id=doc_id,
                method="rule",
                review_status="pending",
            ),
            MeasurementAttribution(
                attribution_id="a4",
                measurement_id="m4-rejected",
                mol_id="CCO",
                doc_id=doc_id,
                method="rule",
                review_status="rejected",
            ),
        ],
    )

    response = app_client.post(
        "/api/v1/capabilities/analyze_series",
        json={"doc_id": doc_id},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["short_id"] == doc_id[:12]
    by_id = {item["mol_id"]: item for item in data["items"]}
    assert set(by_id) == {"CCO", "CCN"}

    a = by_id["CCO"]
    assert a["review_status"] == "confirmed"
    assert a["structure_role"] == "complete"
    assert [activity["measurement_id"] for activity in a["activities"]] == ["m1"]
    activity = a["activities"][0]
    assert activity["value_canonical"] == 12.0
    assert activity["unit_canonical"] == "nM"
    assert activity["target"] == "EGFR"
    assert activity["evidence_ids"] == ["ev-1"]
    assert activity["review_status"] == "accepted"
    assert activity["attribution_review_status"] == "accepted"

    b = by_id["CCN"]
    assert [activity["measurement_id"] for activity in b["activities"]] == ["m2"]
    assert b["activities"][0]["value_canonical"] == 80.0

    every = {
        activity["measurement_id"]
        for item in data["items"]
        for activity in item["activities"]
    }
    assert "m3-orphan" not in every
    assert "m4-rejected" not in every


def test_assign_attribution_writes_an_agent_link(
    app_client: TestClient, tmp_library: Path
) -> None:
    """The agent's adjudication becomes a link; a human link outranks it.

    The write is validated (the reading must exist, the structure must be a
    stored molecule) and gated by the edit token, because it is the one path
    that applies a structure-activity decision without a human.
    """
    from mbforge.contracts.measurement import MeasurementRecord
    from mbforge.db.document_records import insert as insert_document
    from mbforge.db.measurement_store import replace_document_measurements
    from mbforge.db.molecule_store import create as create_molecule
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.service.use_cases.documents.activity_queries import (
        list_activity_records,
    )

    doc_id = "doc-assign-cap"
    DatabaseManager.get(str(tmp_library)).initialize()
    insert_document(
        tmp_library,
        {
            "doc_id": doc_id,
            "file_name": "doc-assign-cap.pdf",
            "title": "doc-assign-cap",
            "page_count": 1,
            "status": "extracted",
            "created_at": "2026-01-01 00:00:00",
        },
    )
    create_molecule(tmp_library, "CCO", "CCO", "CCO", "compound-1", "image")
    replace_document_measurements(
        tmp_library,
        doc_id,
        [
            MeasurementRecord(
                measurement_id="m-1",
                doc_id=doc_id,
                metric="IC50",
                activity_type="IC50",
                original_value=12.0,
                original_unit="nM",
                canonical_value=12.0,
                canonical_unit="nM",
                operator="=",
                reference_raw="化合物1",
                reference_key="1",
                reference_type="compound",
                page_num=1,
                evidence_ids=["ev-1"],
            )
        ],
    )

    payload = {"doc_id": doc_id, "measurement_id": "m-1", "mol_id": "CCO"}
    denied = app_client.post("/api/v1/capabilities/assign_attribution", json=payload)
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "capability_forbidden"

    app_client.get("/api/v1/capabilities/guide")
    token = (
        (tmp_library / ".mbforge" / "capability-token")
        .read_text(encoding="utf-8")
        .strip()
    )

    response = app_client.post(
        "/api/v1/capabilities/assign_attribution",
        json={**payload, "confidence": 0.9},
        headers={"x-mbforge-token": token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["method"] == "agent"
    assert body["data"]["review_status"] == "accepted"
    assert body["data"]["attribution_id"]

    # A structure the library does not hold is refused, not written.
    unknown = app_client.post(
        "/api/v1/capabilities/assign_attribution",
        json={"doc_id": doc_id, "measurement_id": "m-1", "mol_id": "NOPE"},
        headers={"x-mbforge-token": token},
    )
    assert unknown.status_code == 404

    # The reading's effective attribution is the agent link.
    records = list_activity_records(str(tmp_library), doc_id)
    assert len(records) == 1
    assert records[0]["effective_attribution"]["mol_id"] == "CCO"
    assert records[0]["effective_attribution"]["method"] == "agent"


def test_assign_attributions_writes_a_validated_batch(
    app_client: TestClient, tmp_library: Path
) -> None:
    """One inspection pass writes many links, and one bad decision writes none.

    The agent settles tens of readings per pass, so a batch is the difference
    between finishing a document and stopping halfway. Because the batch is the
    path that applies an adjudication without a human, validation is per batch,
    not per item: a reading that does not exist rejects the whole write instead
    of leaving a partial one behind.
    """
    from mbforge.contracts.measurement import MeasurementRecord
    from mbforge.db.document_records import insert as insert_document
    from mbforge.db.measurement_store import replace_document_measurements
    from mbforge.db.molecule_store import create as create_molecule
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.service.use_cases.documents.activity_queries import (
        list_activity_records,
    )

    doc_id = "doc-batch-cap"
    DatabaseManager.get(str(tmp_library)).initialize()
    insert_document(
        tmp_library,
        {
            "doc_id": doc_id,
            "file_name": "doc-batch-cap.pdf",
            "title": "doc-batch-cap",
            "page_count": 1,
            "status": "extracted",
            "created_at": "2026-01-01 00:00:00",
        },
    )
    create_molecule(tmp_library, "CCO", "CCO", "CCO", "compound-1", "image")
    replace_document_measurements(
        tmp_library,
        doc_id,
        [
            MeasurementRecord(
                measurement_id=measurement_id,
                doc_id=doc_id,
                metric="IC50",
                activity_type="IC50",
                original_value=12.0,
                original_unit="nM",
                canonical_value=12.0,
                canonical_unit="nM",
                operator="=",
                reference_raw="化合物1",
                reference_key="1",
                reference_type="compound",
                page_num=1,
                evidence_ids=["ev-1"],
            )
            for measurement_id in ("m-1", "m-2")
        ],
    )

    app_client.get("/api/v1/capabilities/guide")
    token = (
        (tmp_library / ".mbforge" / "capability-token")
        .read_text(encoding="utf-8")
        .strip()
    )
    decisions = [
        {"measurement_id": "m-1", "mol_id": "CCO"},
        {"measurement_id": "m-2", "mol_id": "CCO", "confidence": 0.8},
    ]

    response = app_client.post(
        "/api/v1/capabilities/assign_attributions",
        json={"doc_id": doc_id, "decisions": decisions},
        headers={"x-mbforge-token": token},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["count"] == 2
    assert [item["measurement_id"] for item in body["written"]] == ["m-1", "m-2"]

    records = list_activity_records(str(tmp_library), doc_id)
    assert [row["effective_attribution"]["mol_id"] for row in records] == [
        "CCO",
        "CCO",
    ]

    rejected = app_client.post(
        "/api/v1/capabilities/assign_attributions",
        json={
            "doc_id": doc_id,
            "decisions": [*decisions, {"measurement_id": "m-missing", "mol_id": "CCO"}],
        },
        headers={"x-mbforge-token": token},
    )
    assert rejected.status_code == 404


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
    assert item["payload"] == {"measurement_id": "m-1"}


def test_review_queue_stats_follow_the_document_filter(
    app_client: TestClient, tmp_library: Path
) -> None:
    """The counts must describe the same rows the list returns.

    Filtering the queue by document without filtering the counts reports the
    whole library's backlog as if it belonged to that one document.
    """
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.service.ports import get_repositories

    DatabaseManager.get(str(tmp_library)).initialize()
    repositories = get_repositories(str(tmp_library))
    repositories.review.insert_review_item(
        item_id="unbound-a",
        kind="designation_unbound",
        doc_id="a" * 64,
        page=62,
        bbox=(10.0, 20.0, 30.0, 40.0),
        name="A-2",
        confidence=0.87,
        reasons=["printings disagree"],
        payload={"measurement_id": "m-1"},
    )
    repositories.review.insert_review_item(
        item_id="unbound-b",
        kind="designation_unbound",
        doc_id="b" * 64,
        page=63,
        bbox=(10.0, 20.0, 30.0, 40.0),
        name="B-2",
        confidence=0.87,
        reasons=["printings disagree"],
        payload={"measurement_id": "m-2"},
    )

    response = app_client.post(
        "/api/v1/capabilities/list_review_queue",
        json={"doc_id": "a" * 64},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["pending"] == 1
    assert data["stats"] == [
        {"kind": "designation_unbound", "status": "pending", "count": 1}
    ]

    unfiltered = app_client.post("/api/v1/capabilities/list_review_queue", json={})
    assert unfiltered.json()["data"]["pending"] == 2


def test_review_queue_rejects_an_unknown_kind(app_client: TestClient) -> None:
    """A misspelled kind must not read as "nothing pending"."""
    response = app_client.post(
        "/api/v1/capabilities/list_review_queue",
        json={"kind": "not_a_kind"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"
    assert response.json()["detail"] == "not_a_kind"


def _seed_run(
    root: Path,
    run_id: str,
    *,
    doc_id: str,
    stages: dict[str, str],
    errors: dict[str, str] | None = None,
) -> None:
    """Insert one run's queue nodes without going through the pipeline."""
    from mbforge.db.sqlite.database import DatabaseManager

    db = DatabaseManager.get(str(root))
    db.initialize()
    with db.connection() as conn:
        for stage, status in stages.items():
            conn.execute(
                "INSERT INTO ingest_queue "
                "(id, file_path, doc_id, stage, run_id, status, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{run_id}-{stage}",
                    "doc.pdf",
                    doc_id,
                    stage,
                    run_id,
                    status,
                    (errors or {}).get(stage),
                ),
            )


def test_run_capabilities_expose_failure_reason_and_active_runs(
    app_client: TestClient, tmp_library: Path
) -> None:
    """The agent can diagnose a failed run and find in-flight runs.

    ``runs(action=get)`` without the stage error leaves the model told to
    "inspect the failed stage" with nothing to inspect; ``runs(action=list)``
    is how a resumed session discovers a run whose completion notice it never
    saw.
    """
    _seed_run(
        tmp_library,
        "run-active",
        doc_id="a" * 64,
        stages={"extract": "done", "markdown": "pending"},
    )
    _seed_run(
        tmp_library,
        "run-failed",
        doc_id="b" * 64,
        stages={"extract": "failed", "markdown": "failed"},
        errors={"extract": "layout model missing"},
    )

    failed = app_client.post(
        "/api/v1/capabilities/runs", json={"action": "get", "run_id": "run-failed"}
    )
    assert failed.status_code == 200
    failed_data = failed.json()["data"]
    assert failed_data["status"] == "failed"
    extract = next(node for node in failed_data["nodes"] if node["stage"] == "extract")
    assert extract["error"] == "layout model missing"
    assert extract["updated_at"]

    active = app_client.post("/api/v1/capabilities/runs", json={"action": "list"})
    assert active.status_code == 200
    items = active.json()["data"]["items"]
    assert [item["run_id"] for item in items] == ["run-active"]
    assert items[0]["status"] == "pending"
    assert items[0]["short_id"] == "a" * 12
    assert {node["stage"] for node in items[0]["nodes"]} == {"extract", "markdown"}

    all_runs = app_client.post(
        "/api/v1/capabilities/runs", json={"action": "list", "status": "all"}
    )
    assert {item["run_id"] for item in all_runs.json()["data"]["items"]} == {
        "run-active",
        "run-failed",
    }


def test_get_worker_status_reports_the_model_gate_reason(
    app_client: TestClient, monkeypatch
) -> None:
    """A pending run must be explainable without dev-mode logs."""
    monkeypatch.setattr(
        "mbforge.service.use_cases.pipeline.ingest._model_gate_payload",
        lambda: {
            "ready": False,
            "required": ["moldet"],
            "missing": [{"id": "moldet", "name": "MolDetv2-FT", "status": "not_found"}],
            "reason": "missing models: moldet (not_found)",
        },
    )

    response = app_client.post("/api/v1/capabilities/get_worker_status", json={})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] in {"online", "offline"}
    assert data["model_gate"]["ready"] is False
    assert data["model_gate"]["reason"] == "missing models: moldet (not_found)"


def test_library_briefing_aggregates_server_state(
    app_client: TestClient, tmp_library: Path
) -> None:
    from mbforge.db.sqlite.repositories import create_repositories
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.service.pipeline.artifacts.evidence_models import PageFrame
    from mbforge.service.pipeline.extract.anchors import (
        build_label_anchors,
        build_page_geometry,
    )

    doc = "c" * 64
    evidence = [
        SourceEvidence.create(
            doc_id=doc,
            page=1,
            bbox=(10, 700, 300, 720),
            raw_text="实施例5：目标化合物5的制备",
            kind="sec",
        )
    ]
    create_repositories(tmp_library).anchors.persist(
        doc,
        build_label_anchors(evidence, doc_id=doc),
        build_page_geometry(
            doc, [PageFrame(page=1, width=612, height=792, rotation=0)]
        ),
    )

    response = app_client.post("/api/v1/capabilities/library_briefing", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert {"documents", "active_runs", "worker", "review", "anchors"} <= set(data)
    assert data["anchors"]["anchors"] == 1
    assert data["anchors"]["by_key_space"] == {"example": 1}
    assert isinstance(data["active_runs"], list)
    assert "status" in data["worker"]
    assert "pending" in data["review"]

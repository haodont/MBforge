"""HTTP-level tests for the Markush review router."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mbforge.app import create_app
from mbforge.pipeline.detection.normalization import DetectionSource, NormalizedMolecule
from mbforge.storage.markush_candidates import persist_review_candidates
from mbforge.storage.sqlite.database import DatabaseManager


@pytest.fixture
def client(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    app = create_app()
    return TestClient(app), tmp_path


def _seed(tmp_path) -> str:
    db = DatabaseManager.get(str(tmp_path))
    molecule = NormalizedMolecule(
        canonical_smiles="*c1ccccc1",
        esmiles="*c1ccccc1",
        name="",
        detections=[
            DetectionSource(
                source="image",
                page=1,
                bbox=(10.0, 20.0, 110.0, 220.0),
                image_path="crop.png",
                confidence=0.9,
            )
        ],
    )
    molecule.properties["structure_role"] = "review_required"
    molecule.properties["raw_coref_label"] = "R1"
    molecule.properties["normalized_label"] = "R1"
    molecule.properties["label_kind"] = "r_group"
    with db.mol_conn() as conn:
        persist_review_candidates(
            str(tmp_path), [molecule], conn=conn, recognition_version=1
        )
        return conn.execute(
            "SELECT candidate_id FROM markush_review_candidates LIMIT 1"
        ).fetchone()["candidate_id"]


def test_list_endpoint_returns_seeded_candidate(client) -> None:
    test_client, tmp_path = client
    candidate_id = _seed(tmp_path)
    response = test_client.post(
        "/api/v1/markush/list",
        json={"library_root": str(tmp_path), "review_status": "pending"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["candidate_id"] == candidate_id


def test_get_endpoint_returns_detail(client) -> None:
    test_client, tmp_path = client
    candidate_id = _seed(tmp_path)
    response = test_client.post(
        "/api/v1/markush/get",
        json={"library_root": str(tmp_path), "candidate_id": candidate_id},
    )
    assert response.status_code == 200
    detail = response.json()
    assert detail["candidate_id"] == candidate_id
    assert detail["evidence"]
    assert detail["decisions"]
    assert detail["scaffold_id"] is None
    assert detail["fragment_id"] is None
    assert detail["enumeration_eligible"] is False
    assert detail["enumeration_block_reasons"] == [
        "candidate is not a confirmed scaffold"
    ]


def test_decide_endpoint_confirms_complete(client) -> None:
    test_client, tmp_path = client
    candidate_id = _seed(tmp_path)
    response = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": candidate_id,
            "expected_version": 1,
            "action": "confirm_complete",
            "reason": "looks good",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["new_state"] == "confirmed"
    assert body["molecule_id"]


def test_decide_endpoint_422_on_invalid_transition(client) -> None:
    test_client, tmp_path = client
    candidate_id = _seed(tmp_path)
    # Reopen from pending is illegal
    response = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": candidate_id,
            "expected_version": 1,
            "action": "reopen",
        },
    )
    assert response.status_code == 422


def test_update_endpoint_edits_smiles(client) -> None:
    test_client, tmp_path = client
    candidate_id = _seed(tmp_path)
    response = test_client.post(
        "/api/v1/markush/update",
        json={
            "library_root": str(tmp_path),
            "entity_id": candidate_id,
            "expected_version": 1,
            "smiles": "*c1ccncc1",
            "normalized_label": "R2",
            "note": "fix",
        },
    )
    assert response.status_code == 200
    detail = response.json()
    assert detail["smiles"] == "*c1ccncc1"
    assert detail["normalized_label"] == "R2"


def test_404_response_uses_central_mbforge_error_shape(client) -> None:
    test_client, tmp_path = client
    response = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": "missing",
            "expected_version": 1,
            "action": "reject",
        },
    )
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "not_found"
    assert body["severity"] == "error"


def test_409_response_uses_central_mbforge_error_shape(client) -> None:
    test_client, tmp_path = client
    candidate_id = _seed(tmp_path)
    response = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": candidate_id,
            "expected_version": 99,
            "action": "confirm_complete",
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "conflict"

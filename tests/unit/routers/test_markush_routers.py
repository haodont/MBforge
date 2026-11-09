"""HTTP-level tests for the Markush review router.

Covered module: ``mbforge.api.http.markush.review`` (list / get / decide /
update).

Protects the review queue projection and the illegal-transition /
version-conflict / not-found envelopes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mbforge.db.markush_candidates import persist_review_candidates
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource
from mbforge.server.app import create_app


@pytest.fixture
def client(tmp_path):
    DatabaseManager.get(str(tmp_path)).initialize()
    return TestClient(create_app()), tmp_path


# --- review queue (scaffold review) ---


def _seed_review_candidate(tmp_path) -> str:
    """Persist one review_required candidate and return its id."""
    db = DatabaseManager.get(str(tmp_path))
    molecule = Molecule(
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


def test_review_queue_lists_and_returns_the_candidate_detail(client) -> None:
    """``/markush/list`` pages the pending candidate; ``/get`` returns its detail."""
    test_client, tmp_path = client
    candidate_id = _seed_review_candidate(tmp_path)

    response = test_client.post(
        "/api/v1/markush/list",
        json={"library_root": str(tmp_path), "review_status": "pending"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["candidate_id"] == candidate_id

    detail = test_client.post(
        "/api/v1/markush/get",
        json={"library_root": str(tmp_path), "candidate_id": candidate_id},
    ).json()
    assert detail["candidate_id"] == candidate_id
    assert detail["evidence"]
    assert detail["decisions"]
    assert detail["scaffold_id"] is None
    assert detail["fragment_id"] is None


def test_review_update_edits_smiles_and_normalized_label(client) -> None:
    """``/markush/update`` edits the editable fields of a pending candidate."""
    test_client, tmp_path = client
    candidate_id = _seed_review_candidate(tmp_path)
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


def test_review_decide_confirms_and_reports_transition_errors(client) -> None:
    """Confirm mints a molecule; illegal transitions, stale versions and unknown
    ids answer with the central ``success``/``error_code`` envelope."""
    test_client, tmp_path = client
    candidate_id = _seed_review_candidate(tmp_path)
    root = str(tmp_path)

    # Reopen from pending is an illegal transition.
    illegal = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": root,
            "entity_id": candidate_id,
            "expected_version": 1,
            "action": "reopen",
        },
    )
    assert illegal.status_code == 422

    confirmed = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": root,
            "entity_id": candidate_id,
            "expected_version": 1,
            "action": "confirm_complete",
            "reason": "looks good",
        },
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["new_state"] == "confirmed"
    assert body["molecule_id"]

    stale = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": root,
            "entity_id": candidate_id,
            "expected_version": 99,
            "action": "confirm_complete",
        },
    )
    assert stale.status_code == 409
    body = stale.json()
    assert body["success"] is False
    assert body["error_code"] == "conflict"

    missing = test_client.post(
        "/api/v1/markush/decide",
        json={
            "library_root": root,
            "entity_id": "missing",
            "expected_version": 1,
            "action": "reject",
        },
    )
    assert missing.status_code == 404
    body = missing.json()
    assert body["success"] is False
    assert body["error_code"] == "not_found"
    assert body["severity"] == "error"

"""HTTP-level tests for the Markush routers.

Covered modules:
    ``mbforge.api.http.markush.review``      (list / get / decide / update)
    ``mbforge.api.http.markush.sites``       (sites/create)
    ``mbforge.api.http.markush.enumeration`` (preview / run / results / generated-decide)

The three share one fixture and form one workflow: a reviewed candidate
becomes a confirmed scaffold, the scaffold carries confirmed sites, and
the sites are enumerated into generated candidates.

Protects: the review queue projection and the illegal-transition /
version-conflict / not-found envelopes, the "confirmed scaffold only"
gate on site creation, the enumeration authorization contract (every
scaffold, site and fragment confirmed and linked before a run is
written), the bounded ``run_id`` lookup, and the single-shot
confirm/reject of a generated candidate.
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
    assert detail["enumeration_eligible"] is False
    assert detail["enumeration_block_reasons"] == [
        "candidate is not a confirmed scaffold"
    ]


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


# --- sites ---


def _seed_site_relations(tmp_path) -> str:
    """Seed one confirmed scaffold + fragment and return the scaffold id."""
    db = DatabaseManager.get(str(tmp_path))
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES (?, 'doc-1', ?, 'confirmed')
            """,
            ("sc-1", "*c1ccc(*)cc1"),
        )
        conn.execute(
            """
            INSERT INTO markush_fragments
                (fragment_id, doc_id, smiles, status)
            VALUES (?, 'doc-1', '*C', 'confirmed')
            """,
            ("fr-1",),
        )
        conn.commit()
    return "sc-1"


def test_sites_create_accepts_confirmed_scaffold_and_rejects_pending(client) -> None:
    """A site is created on a confirmed scaffold; a pending scaffold is 422."""
    test_client, tmp_path = client
    _seed_site_relations(tmp_path)
    response = test_client.post(
        "/api/v1/markush/sites/create",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-1",
            "site_label": "R1",
            "atom_map_num": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["site_label"] == "R1"
    assert body["atom_map_num"] == 1

    db = DatabaseManager.get(str(tmp_path))
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES ('sc-p', 'doc-1', '*c1ccc(*)cc1', 'pending')
            """
        )
        conn.commit()
    rejected = test_client.post(
        "/api/v1/markush/sites/create",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-p",
            "site_label": "R1",
            "atom_map_num": 1,
        },
    )
    assert rejected.status_code == 422
    body = rejected.json()
    assert body["success"] is False
    assert body["error_code"] == "validation_error"


# --- enumeration ---


def _seed_confirmed_relations(tmp_path) -> None:
    db = DatabaseManager.get(str(tmp_path))
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES ('sc-1', 'doc-1', '[*:1]C1CCCCC1', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_sites
                (site_id, scaffold_id, site_label, atom_map_num, status)
            VALUES ('site-1', 'sc-1', 'R1', 1, 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_fragments
                (fragment_id, doc_id, label, smiles, status)
            VALUES ('frag-1', 'doc-1', 'F', 'F', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_options
                (option_id, site_id, fragment_id, status)
            VALUES ('opt-1', 'site-1', 'frag-1', 'confirmed')
            """
        )
        conn.commit()


def _count_runs(tmp_path) -> int:
    db = DatabaseManager.get(str(tmp_path))
    with db.mol_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM markush_generation_runs").fetchone()[
            0
        ]


def _selection(fragments):
    return [
        {
            "site_label": "R1",
            "atom_map_num": 1,
            "fragments": fragments,
        }
    ]


def test_enumeration_preview_and_run_for_confirmed_relation(client) -> None:
    """Preview counts without writing; run persists the generated candidate."""
    test_client, tmp_path = client
    _seed_confirmed_relations(tmp_path)
    root = str(tmp_path)

    preview = test_client.post(
        "/api/v1/markush/enumeration/preview",
        json={
            "library_root": root,
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-1"]),
            "requested_limit": 10,
        },
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["theoretical_count"] == 1
    assert body["truncated"] is False

    run = test_client.post(
        "/api/v1/markush/enumeration/run",
        json={
            "library_root": root,
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-1"]),
            "requested_limit": 10,
        },
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["written_count"] == 1
    assert body["run_id"]


def test_enumeration_rejects_invalid_requests_without_writing_runs(client) -> None:
    """Unauthorized selections and a missing ``run_id`` are 422; no run is written."""
    test_client, tmp_path = client
    root = str(tmp_path)
    _seed_confirmed_relations(tmp_path)

    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds(scaffold_id, doc_id, smiles, status)
            VALUES ('sc-2', 'doc-2', '[*:1]CC', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_fragments(fragment_id, doc_id, smiles, status)
            VALUES ('frag-2', 'doc-2', 'Cl', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_scaffolds(scaffold_id, doc_id, smiles, status)
            VALUES ('sc-p', 'doc-1', '[*:1]C1CCCCC1', 'pending')
            """
        )
        conn.commit()

    foreign = test_client.post(
        "/api/v1/markush/enumeration/run",
        json={
            "library_root": root,
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-2"]),
            "requested_limit": 10,
        },
    )
    assert foreign.status_code == 422
    assert _count_runs(root) == 0

    unconfirmed = test_client.post(
        "/api/v1/markush/enumeration/run",
        json={
            "library_root": root,
            "scaffold_id": "sc-p",
            "selection": _selection(["frag-1"]),
            "requested_limit": 10,
        },
    )
    assert unconfirmed.status_code == 422
    body = unconfirmed.json()
    assert body["success"] is False
    assert body["error_code"] == "markush_enumeration_invalid"
    assert _count_runs(root) == 0

    missing_run = test_client.post(
        "/api/v1/markush/enumeration/results",
        json={"library_root": root},
    )
    assert missing_run.status_code == 422


def _run_and_get_generated_id(test_client, tmp_path) -> str:
    _seed_confirmed_relations(tmp_path)
    run_response = test_client.post(
        "/api/v1/markush/enumeration/run",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-1"]),
            "requested_limit": 10,
        },
    )
    run_id = run_response.json()["run_id"]
    results = test_client.post(
        "/api/v1/markush/enumeration/results",
        json={"library_root": str(tmp_path), "run_id": run_id},
    ).json()["items"]
    return results[0]["generated_id"]


def test_generated_decision_confirms_once(client) -> None:
    """Confirm promotes a generated candidate; a second decision is refused."""
    test_client, tmp_path = client
    generated_id = _run_and_get_generated_id(test_client, tmp_path)
    response = test_client.post(
        "/api/v1/markush/generated/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": generated_id,
            "action": "confirm",
            "reason": "ok",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["generated_id"] == generated_id
    assert body["review_status"] == "confirmed"
    assert body["mol_id"] == generated_id

    second = test_client.post(
        "/api/v1/markush/generated/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": generated_id,
            "action": "reject",
            "reason": "retry",
        },
    )
    assert second.status_code == 422
    body = second.json()
    assert body["success"] is False
    assert body["error_code"] == "markush_enumeration_invalid"

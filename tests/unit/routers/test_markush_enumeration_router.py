"""HTTP-level tests for the Markush enumeration router.

The enumeration API is the enforcement point of the Markush state
contract: every scaffold, site, and fragment must be ``confirmed`` and
linked through a confirmed option or mount before a run may be created.
Invalid selections must be rejected with HTTP 422 without persisting a
generation run.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mbforge.adapters.persistence.sqlite.database import DatabaseManager
from mbforge.app import create_app


@pytest.fixture
def client(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    app = create_app()
    return TestClient(app), tmp_path


def _seed_confirmed_relations(tmp_path):
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


def test_preview_returns_count_for_confirmed_relation(client) -> None:
    test_client, tmp_path = client
    _seed_confirmed_relations(tmp_path)
    response = test_client.post(
        "/api/v1/markush/enumeration/preview",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-1"]),
            "requested_limit": 10,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["theoretical_count"] == 1
    assert body["truncated"] is False


def test_run_returns_generated_count_for_confirmed_relation(client) -> None:
    test_client, tmp_path = client
    _seed_confirmed_relations(tmp_path)
    response = test_client.post(
        "/api/v1/markush/enumeration/run",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-1"]),
            "requested_limit": 10,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["written_count"] == 1
    assert body["run_id"]


def test_run_rejects_unconfirmed_scaffold_without_writing_run(client) -> None:
    test_client, tmp_path = client
    # Scaffold exists but is pending, and no relation rows exist.
    db = DatabaseManager.get(str(tmp_path))
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES ('sc-1', 'doc-1', '[*:1]C1CCCCC1', 'pending')
            """
        )
        conn.commit()
    response = test_client.post(
        "/api/v1/markush/enumeration/run",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-1"]),
            "requested_limit": 10,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "markush_enumeration_invalid"
    assert _count_runs(tmp_path) == 0


def test_run_rejects_fragment_from_other_scaffold(client) -> None:
    test_client, tmp_path = client
    _seed_confirmed_relations(tmp_path)
    db = DatabaseManager.get(str(tmp_path))
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
        conn.commit()
    response = test_client.post(
        "/api/v1/markush/enumeration/run",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-1",
            "selection": _selection(["frag-2"]),
            "requested_limit": 10,
        },
    )
    assert response.status_code == 422
    assert _count_runs(tmp_path) == 0


def test_results_requires_run_id(client) -> None:
    test_client, tmp_path = client
    response = test_client.post(
        "/api/v1/markush/enumeration/results",
        json={"library_root": str(tmp_path)},
    )
    assert response.status_code == 422


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


def test_generated_confirm_returns_mol_id(client) -> None:
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


def test_generated_cannot_be_decided_twice(client) -> None:
    test_client, tmp_path = client
    generated_id = _run_and_get_generated_id(test_client, tmp_path)
    first = test_client.post(
        "/api/v1/markush/generated/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": generated_id,
            "action": "reject",
            "reason": "no",
        },
    )
    assert first.status_code == 200
    second = test_client.post(
        "/api/v1/markush/generated/decide",
        json={
            "library_root": str(tmp_path),
            "entity_id": generated_id,
            "action": "confirm",
            "reason": "retry",
        },
    )
    assert second.status_code == 422
    body = second.json()
    assert body["success"] is False
    assert body["error_code"] == "markush_enumeration_invalid"

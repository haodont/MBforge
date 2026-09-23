"""HTTP-level tests for the Markush sites/options/mounts router (Phase 4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mbforge.adapters.persistence.sqlite.database import DatabaseManager
from mbforge.app import create_app


@pytest.fixture
def client(tmp_path):
    DatabaseManager.get(str(tmp_path)).initialize()
    app = create_app()
    return TestClient(app), tmp_path


def _seed(tmp_path, *, scaffold_smiles: str = "*c1ccc(*)cc1") -> str:
    db = DatabaseManager.get(str(tmp_path))
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES (?, 'doc-1', ?, 'confirmed')
            """,
            ("sc-1", scaffold_smiles),
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


def test_create_site_succeeds(client) -> None:
    test_client, tmp_path = client
    _seed(tmp_path)
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


def test_create_site_rejects_pending_scaffold(client) -> None:
    test_client, tmp_path = client
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
    response = test_client.post(
        "/api/v1/markush/sites/create",
        json={
            "library_root": str(tmp_path),
            "scaffold_id": "sc-p",
            "site_label": "R1",
            "atom_map_num": 1,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "validation_error"

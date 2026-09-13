from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mbforge.storage.sqlite.database import DatabaseManager


def _assert_error(response, expected_status: int, expected_error_code: str) -> dict:
    assert response.status_code == expected_status, response.text
    data = response.json()
    assert data["success"] is False
    assert data["error_code"] == expected_error_code
    return data


def test_molecule_create_and_get(app_client: TestClient, tmp_library) -> None:
    root = str(tmp_library)
    resp = app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO", "name": "Ethanol"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    mol_id = data["mol_id"]

    resp = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": mol_id},
    )
    assert resp.status_code == 200
    assert resp.json()["molecule"]["smiles"] == "CCO"


def test_molecule_list_applies_server_filters_and_sorting(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    for mol_id, name in (("m1", "Zeta"), ("m2", "Alpha"), ("m3", "Beta")):
        response = app_client.post(
            "/api/v1/molecule/create",
            json={
                "library_root": root,
                "mol_id": mol_id,
                "smiles": "CCO",
                "name": name,
            },
        )
        assert response.status_code == 200
    app_client.put(
        "/api/v1/molecule/m3",
        json={"library_root": root, "status": "rejected", "activity": 10},
    )

    response = app_client.post(
        "/api/v1/molecule/list",
        json={
            "library_root": root,
            "page": 1,
            "page_size": 1,
            "sort_field": "name",
            "sort_direction": "asc",
            "status": "rejected",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["matching_ids"] == ["m3"]
    assert data["items"][0]["name"] == "Beta"
    assert "manual" in data["source_types"]


def test_molecule_list_backfills_source_doc_from_evidence(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO", "mol_id": "CCO"},
    )
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO evidence
                (canonical_smiles, mol_id, doc_id, context_text, role, kind)
            VALUES ('CCO', 'CCO', 'doc-42', 'nearby text', 'detected', 'figure')
            """
        )

    response = app_client.post(
        "/api/v1/molecule/list",
        json={"library_root": root, "page": 1, "page_size": 10},
    )

    assert response.status_code == 200
    molecule = response.json()["items"][0]
    assert molecule["source_doc"] == "doc-42"

    resp = app_client.post("/api/v1/molecule/stats", json={"library_root": root})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_molecule_update_and_delete(app_client: TestClient, tmp_library) -> None:
    root = str(tmp_library)
    resp = app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO"},
    )
    mol_id = resp.json()["mol_id"]
    resp = app_client.put(
        f"/api/v1/molecule/{mol_id}",
        json={"library_root": root, "name": "Updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": mol_id},
    )
    assert resp.json()["molecule"]["name"] == "Updated"


def test_molecule_bulk_status_updates_existing_records(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    for mol_id in ("m1", "m2"):
        app_client.post(
            "/api/v1/molecule/create",
            json={"library_root": root, "mol_id": mol_id, "smiles": "CCO"},
        )

    response = app_client.put(
        "/api/v1/molecule/bulk-status",
        json={
            "library_root": root,
            "mol_ids": ["m1", "m2", "missing"],
            "status": "confirmed",
        },
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert response.json()["skipped"] == 1


def test_molecule_bulk_delete_removes_records(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    for mol_id in ("m1", "m2"):
        app_client.post(
            "/api/v1/molecule/create",
            json={"library_root": root, "mol_id": mol_id, "smiles": "CCO"},
        )

    response = app_client.post(
        "/api/v1/molecule/bulk-delete",
        json={"library_root": root, "mol_ids": ["m1", "m2", "missing"]},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] == 2
    listed = app_client.post(
        "/api/v1/molecule/list",
        json={"library_root": root, "page": 1, "page_size": 10},
    )
    assert listed.json()["total"] == 0


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/api/v1/molecule/get", {"mol_id": "no-such-mol"}),
        ("/api/v1/molecule/evidence", {"canonical_smiles": "no-such-mol"}),
    ],
)
def test_molecule_unknown_returns_404(
    app_client: TestClient, tmp_library, endpoint: str, payload: dict
) -> None:
    root = str(tmp_library)
    _assert_error(
        app_client.post(endpoint, json={"library_root": root, **payload}),
        404,
        "not_found",
    )


def test_molecule_update_no_fields_returns_422(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    resp = app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO"},
    )
    mol_id = resp.json()["mol_id"]
    _assert_error(
        app_client.put(f"/api/v1/molecule/{mol_id}", json={"library_root": root}),
        422,
        "validation_error",
    )


def test_molecule_update_with_tags_and_properties(
    app_client: TestClient, tmp_library
) -> None:
    """Frontend ``tags`` and ``properties`` are persisted and returned parsed."""
    root = str(tmp_library)
    resp = app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO", "mol_id": "CCO"},
    )
    mol_id = resp.json()["mol_id"]

    resp = app_client.put(
        f"/api/v1/molecule/{mol_id}",
        json={
            "library_root": root,
            "tags": ["frag-1", "frag-2"],
            "properties": {"mw": 46.07},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": mol_id},
    )
    molecule = resp.json()["molecule"]
    assert molecule["tags"] == ["frag-1", "frag-2"]
    assert molecule["properties"] == {"mw": 46.07}


def test_molecule_get_parses_json_text_columns(
    app_client: TestClient, tmp_library
) -> None:
    """JSON-encoded TEXT columns are parsed and ``labels`` is mapped to ``tags``."""
    root = str(tmp_library)
    app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO", "mol_id": "CCO"},
    )
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        conn.execute(
            "UPDATE molecules SET labels = ?, properties = ? WHERE mol_id = ?",
            ('["tag-1"]', '{"mw": 46.07}', "CCO"),
        )

    resp = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": "CCO"},
    )
    molecule = resp.json()["molecule"]
    assert molecule["tags"] == ["tag-1"]
    assert molecule["properties"] == {"mw": 46.07}
    assert "labels" not in molecule


def test_molecule_search_text_mode_uses_fts5(
    app_client: TestClient, tmp_library
) -> None:
    """Text mode should match compound names via FTS5."""
    root = str(tmp_library)
    app_client.post(
        "/api/v1/molecule/create",
        json={
            "library_root": root,
            "smiles": "CCO",
            "mol_id": "CCO",
            "name": "ethanol",
        },
    )
    app_client.post(
        "/api/v1/molecule/create",
        json={
            "library_root": root,
            "smiles": "c1ccccc1",
            "mol_id": "benzene",
            "name": "benzene",
        },
    )

    resp = app_client.post(
        "/api/v1/molecule/search",
        json={"library_root": root, "query": "ethanol", "mode": "text"},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["name"] == "ethanol"


def test_molecule_search_auto_detects_smiles_as_substructure(
    app_client: TestClient, tmp_library
) -> None:
    """Auto mode should treat a valid SMILES as a substructure query."""
    root = str(tmp_library)
    app_client.post(
        "/api/v1/molecule/create",
        json={
            "library_root": root,
            "smiles": "CCO",
            "mol_id": "CCO",
            "name": "ethanol",
        },
    )
    app_client.post(
        "/api/v1/molecule/create",
        json={
            "library_root": root,
            "smiles": "c1ccccc1",
            "mol_id": "benzene",
            "name": "benzene",
        },
    )

    resp = app_client.post(
        "/api/v1/molecule/search",
        json={"library_root": root, "query": "CCO", "mode": "auto"},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert any(r["mol_id"] == "CCO" for r in results)
    assert not any(r["mol_id"] == "benzene" for r in results)


def test_molecule_search_similarity_mode_returns_scores(
    app_client: TestClient, tmp_library
) -> None:
    """Similarity mode should return molecules ranked by Tanimoto similarity."""
    root = str(tmp_library)
    app_client.post(
        "/api/v1/molecule/create",
        json={
            "library_root": root,
            "smiles": "CCO",
            "mol_id": "CCO",
            "name": "ethanol",
        },
    )
    app_client.post(
        "/api/v1/molecule/create",
        json={
            "library_root": root,
            "smiles": "CCCO",
            "mol_id": "propanol",
            "name": "propanol",
        },
    )

    resp = app_client.post(
        "/api/v1/molecule/search",
        json={
            "library_root": root,
            "query": "CCO",
            "mode": "similarity",
            "similarity_threshold": 0.0,
        },
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2
    assert results[0]["similarity"] >= results[1]["similarity"]


def test_molecule_by_location_uses_detection_cache_and_converts_page(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "mol_id": "m1", "smiles": "CCO", "name": "ethanol"},
    )
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        conn.execute(
            "UPDATE molecules SET canonical_smiles = ? WHERE mol_id = ?",
            ("CCO", "m1"),
        )
        conn.execute(
            """
            INSERT INTO evidence
                (canonical_smiles, mol_id, doc_id, page, bbox_x0, bbox_y0,
                 bbox_x1, bbox_y1, kind, confidence, crop_relpath)
            VALUES ('CCO', 'm1', 'doc-1', 3, 10, 20, 40, 60, 'figure', 0.91,
                    'crop.png')
            """
        )
        conn.execute(
            """
            INSERT INTO molecule_detections
                (mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 conf_moldet, vlm_verified_esmiles, crop_relpath)
            VALUES ('m1', 'doc-1', 2, 10, 20, 40, 60, 0.82, 'CCO', 'crop.png')
            """
        )

    response = app_client.get(
        "/api/v1/molecule/by-location",
        params={
            "library_root": root,
            "doc_id": "doc-1",
            "page": 3,
            "x0": 15,
            "y0": 25,
            "x1": 35,
            "y1": 55,
        },
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    # Legacy ``evidence`` is not a location-query fallback; the interactive
    # detection-cache row is the only match in this fixture.
    assert len(matches) == 1
    assert {match["page"] for match in matches} == {3}
    assert all(match["mol_id"] == "m1" for match in matches)
    assert all(match["name"] == "ethanol" for match in matches)

    miss = app_client.get(
        "/api/v1/molecule/by-location",
        params={
            "library_root": root,
            "doc_id": "doc-1",
            "page": 2,
            "x0": 100,
            "y0": 100,
            "x1": 120,
            "y1": 120,
        },
    )
    assert miss.status_code == 200
    assert miss.json()["matches"] == []


def test_molecule_smiles_correction_is_audited_and_readable(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "mol_id": "m1", "smiles": "CCO"},
    )

    response = app_client.put(
        "/api/v1/molecule/m1",
        json={"library_root": root, "smiles": "CCN"},
    )
    assert response.status_code == 200
    molecule = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": "m1"},
    ).json()["molecule"]
    assert molecule["smiles"] == "CCN"

    corrections = app_client.get(
        "/api/v1/molecule/m1/corrections",
        params={"library_root": root},
    )
    assert corrections.status_code == 200
    assert corrections.json()["corrections"] == [
        {
            "correction_id": 1,
            "mol_id": "m1",
            "field": "smiles",
            "old_value": "CCO",
            "new_value": "CCN",
            "source": "molecule_update",
            "created_at": corrections.json()["corrections"][0]["created_at"],
        }
    ]

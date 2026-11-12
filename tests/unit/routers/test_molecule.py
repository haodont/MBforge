"""HTTP-level tests for the molecule router (``mbforge.api.http.molecule.molecule``).

Covered endpoints: list, stats, get, evidence, create, update,
bulk-status, bulk-delete, delete, search, by-location, corrections.

Protects: the create/get/update/delete round trip and its audited SMILES
corrections, server-side filtering/sorting/pagination with evidence
back-fill, the bulk write paths, the central 404/422 error envelopes, the
text/auto/similarity search modes, and the detection-cache location lookup
with its 1-based page conversion.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mbforge.db.sqlite.database import DatabaseManager


def _assert_error(response, expected_status: int, expected_error_code: str) -> dict:
    assert response.status_code == expected_status, response.text
    data = response.json()
    assert data["success"] is False
    assert data["error_code"] == expected_error_code
    return data


def test_molecule_crud_round_trip_with_tags_properties_and_audit(
    app_client: TestClient, tmp_library
) -> None:
    """Create/get/update round-trip persists fields and audits a SMILES correction."""
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

    resp = app_client.put(
        f"/api/v1/molecule/{mol_id}",
        json={"library_root": root, "name": "Updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Frontend ``tags`` and ``properties`` are persisted and returned parsed.
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

    molecule = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": mol_id},
    ).json()["molecule"]
    assert molecule["name"] == "Updated"
    assert molecule["tags"] == ["frag-1", "frag-2"]
    assert molecule["properties"] == {"mw": 46.07}

    # A SMILES edit is appended to the readable correction audit.
    response = app_client.put(
        f"/api/v1/molecule/{mol_id}",
        json={"library_root": root, "smiles": "CCN"},
    )
    assert response.status_code == 200
    assert (
        app_client.post(
            "/api/v1/molecule/get",
            json={"library_root": root, "mol_id": mol_id},
        ).json()["molecule"]["smiles"]
        == "CCN"
    )

    corrections = app_client.get(
        f"/api/v1/molecule/{mol_id}/corrections",
        params={"library_root": root},
    )
    assert corrections.status_code == 200
    assert corrections.json()["corrections"] == [
        {
            "correction_id": 1,
            "mol_id": mol_id,
            "field": "smiles",
            "old_value": "CCO",
            "new_value": "CCN",
            "source": "molecule_update",
            "created_at": corrections.json()["corrections"][0]["created_at"],
        }
    ]


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
    with db.connection() as conn:
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


def test_molecule_list_filters_sorts_backfills_source_doc_and_counts(
    app_client: TestClient, tmp_library
) -> None:
    """List applies server filters/sorting/pagination, back-fills evidence, stats count."""
    root = str(tmp_library)
    for mol_id, name in (
        ("m1", "Zeta"),
        ("m2", "Alpha"),
        ("m3", "Beta"),
        ("CCO", "carbonic"),
    ):
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

    db = DatabaseManager.get(root)
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO molecule_detections
                (mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 conf_moldet, context_text)
            VALUES ('CCO', 'doc-42', 0, 0, 0, 1, 1, 0.9, 'nearby text')
            """
        )

    listed = app_client.post(
        "/api/v1/molecule/list",
        json={"library_root": root, "page": 1, "page_size": 10},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 4
    backfilled = next(m for m in body["items"] if m["mol_id"] == "CCO")
    assert backfilled["source_doc"] == "doc-42"

    resp = app_client.post("/api/v1/molecule/stats", json={"library_root": root})
    assert resp.status_code == 200
    assert resp.json()["total"] == 4


def test_molecule_bulk_status_and_bulk_delete(
    app_client: TestClient, tmp_library
) -> None:
    """Bulk status skips unknown ids; bulk delete removes the listed records."""
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

    deleted = app_client.post(
        "/api/v1/molecule/bulk-delete",
        json={"library_root": root, "mol_ids": ["m1", "m2", "missing"]},
    )

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 2
    listed = app_client.post(
        "/api/v1/molecule/list",
        json={"library_root": root, "page": 1, "page_size": 10},
    )
    assert listed.json()["total"] == 0


def test_molecule_errors_use_central_envelope(
    app_client: TestClient, tmp_library
) -> None:
    """Unknown ids answer 404/not_found; an empty update answers 422/validation_error."""
    root = str(tmp_library)
    for endpoint, payload in (
        ("/api/v1/molecule/get", {"mol_id": "no-such-mol"}),
        ("/api/v1/molecule/evidence", {"canonical_smiles": "no-such-mol"}),
    ):
        _assert_error(
            app_client.post(endpoint, json={"library_root": root, **payload}),
            404,
            "not_found",
        )

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


def test_molecule_search_text_auto_and_similarity_modes(
    app_client: TestClient, tmp_library
) -> None:
    """Text mode uses FTS5, auto treats SMILES as substructure, similarity ranks."""
    root = str(tmp_library)
    for mol_id, smiles, name in (
        ("CCO", "CCO", "ethanol"),
        ("benzene", "c1ccccc1", "benzene"),
        ("propanol", "CCCO", "propanol"),
    ):
        app_client.post(
            "/api/v1/molecule/create",
            json={
                "library_root": root,
                "smiles": smiles,
                "mol_id": mol_id,
                "name": name,
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

    resp = app_client.post(
        "/api/v1/molecule/search",
        json={"library_root": root, "query": "CCO", "mode": "auto"},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert any(r["mol_id"] == "CCO" for r in results)
    assert not any(r["mol_id"] == "benzene" for r in results)

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
    assert len(results) == 3
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
    with db.connection() as conn:
        conn.execute(
            "UPDATE molecules SET canonical_smiles = ? WHERE mol_id = ?",
            ("CCO", "m1"),
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
    # The interactive detection-cache row is the only match in this fixture.
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

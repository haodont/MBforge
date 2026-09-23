"""detection-cache router: real read/clear/stats against molecule_detections."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.adapters.persistence.sqlite.database import DatabaseManager
from mbforge.application.dto.detection_cache import DetectionInput


def _seed_detection(library_root: Path, doc_id: str = "doc1", page: int = 1) -> None:
    db = DatabaseManager.get(library_root)
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO molecule_detections
                (mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 crop_relpath, conf_moldet, conf_molscribe, vlm_verified_esmiles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            # mol_id NULL avoids FK to molecules for cache-only rows
            (None, doc_id, page, 0.1, 0.2, 0.3, 0.4, "crop.png", 0.9, 0.8, "CCO"),
        )


def test_detection_cache_get_stats_clear(
    app_client: TestClient, tmp_library: Path
) -> None:
    _seed_detection(tmp_library)

    stats = app_client.post(
        "/api/v1/detection-cache/stats",
        json={"library_root": str(tmp_library)},
    )
    assert stats.status_code == 200
    body = stats.json()
    assert body["cached_page_count"] >= 1
    assert body["cached_doc_count"] >= 1

    got = app_client.post(
        "/api/v1/detection-cache/get",
        json={"library_root": str(tmp_library), "doc_id": "doc1", "page": 1},
    )
    assert got.status_code == 200
    data = got.json()
    assert data["count"] == 1
    assert data["source"] == "cache"
    assert len(data["results"]) == 1
    assert data["results"][0]["esmiles"] == "CCO"
    # back-compat alias
    assert len(data["detections"]) == 1

    cleared = app_client.post(
        "/api/v1/detection-cache/clear-doc",
        json={"library_root": str(tmp_library), "doc_id": "doc1"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["success"] is True
    assert cleared.json()["cleared"] >= 1

    after = app_client.post(
        "/api/v1/detection-cache/get",
        json={"library_root": str(tmp_library), "doc_id": "doc1", "page": 1},
    )
    assert after.json()["count"] == 0
    assert after.json()["source"] == "cache_miss"


def test_detection_save_unknown_mol_id_falls_back_to_null(
    app_client: TestClient, tmp_library: Path
) -> None:
    """FE sends display names as mol_id; unknown ids must not trip the FK."""
    resp = app_client.post(
        "/api/v1/detection-cache/save",
        json={
            "library_root": str(tmp_library),
            "detections": [
                {
                    "mol_id": "Mol_001",
                    "doc_id": "doc1",
                    "page": 2,
                    "bbox_x0": 0.1,
                    "bbox_y0": 0.2,
                    "bbox_x1": 0.3,
                    "bbox_y1": 0.4,
                    "conf_moldet": 0.9,
                    "conf_molscribe": 0.8,
                    "vlm_verified_esmiles": "CCO",
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    got = app_client.post(
        "/api/v1/detection-cache/get",
        json={"library_root": str(tmp_library), "doc_id": "doc1", "page": 2},
    )
    assert got.json()["count"] == 1
    assert got.json()["results"][0]["mol_id"] is None
    assert got.json()["results"][0]["esmiles"] == "CCO"


def test_detection_save_keeps_existing_mol_id(
    app_client: TestClient, tmp_library: Path
) -> None:
    db = DatabaseManager.get(tmp_library)
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, source_type) "
            "VALUES ('CCO', 'CCO', 'image')"
        )

    resp = app_client.post(
        "/api/v1/detection-cache/save",
        json={
            "library_root": str(tmp_library),
            "detections": [
                {
                    "mol_id": "CCO",
                    "doc_id": "doc1",
                    "page": 3,
                    "bbox_x0": 0.1,
                    "bbox_y0": 0.2,
                    "bbox_x1": 0.3,
                    "bbox_y1": 0.4,
                    "conf_moldet": 0.9,
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    got = app_client.post(
        "/api/v1/detection-cache/get",
        json={"library_root": str(tmp_library), "doc_id": "doc1", "page": 3},
    )
    assert got.json()["results"][0]["mol_id"] == "CCO"


def test_detection_cache_extract_page_accepts_frontend_aliases(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Frontend sends ``libraryRoot`` / ``docId`` plus ignored image metadata."""
    _seed_detection(tmp_library)
    resp = app_client.post(
        "/api/v1/detection-cache/extract-page",
        json={
            "libraryRoot": str(tmp_library),
            "docId": "doc1",
            "page": 1,
            "image_base64": "data:image/png;base64,abc",
            "page_w_pts": 612.0,
            "page_h_pts": 792.0,
            "image_w": 100,
            "image_h": 100,
            "force": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_detection_cache_batch_scan_not_implemented(
    app_client: TestClient, tmp_library: Path
) -> None:
    resp = app_client.post(
        "/api/v1/detection-cache/batch-scan",
        json={"library_root": str(tmp_library), "doc_ids": ["doc1"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "not implemented" in body["error"]
    assert body["errors"] == ["not_implemented"]


def test_detection_input_accepts_esmiles_alias() -> None:
    """DetectionInput accepts the frontend ``esmiles`` / ``smiles`` aliases."""
    det = DetectionInput(doc_id="doc1", page=1, esmiles="CCO")
    assert det.vlm_verified_esmiles == "CCO"

    det2 = DetectionInput(doc_id="doc1", page=1, smiles="CCO")
    assert det2.vlm_verified_esmiles == "CCO"

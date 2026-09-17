from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_library_status(app_client: TestClient) -> None:
    resp = app_client.get("/api/v1/library/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert "root" in data


def test_library_configure(app_client: TestClient, tmp_path: Path, monkeypatch) -> None:
    # Isolate the global settings file so the test does not overwrite user config.
    from mbforge.utils import config

    settings_path = tmp_path / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "_SETTINGS_PATH", settings_path)

    root = str(tmp_path / "new_lib")
    resp = app_client.post("/api/v1/library/configure", json={"root": root})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_library_import_and_list(app_client: TestClient) -> None:
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        data={"title": "Test Paper"},
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    doc_id = data["document"]["doc_id"]

    resp = app_client.post("/api/v1/library/documents", json={})
    assert resp.status_code == 200
    ids = {d["doc_id"] for d in resp.json()["documents"]}
    assert doc_id in ids


def test_library_import_does_not_auto_enqueue(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Import only registers the document; enqueue is a separate step."""
    from mbforge.storage.sqlite.database import DatabaseManager

    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("queued.pdf", b"%PDF-1.4 fake pdf", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["document"]["doc_id"]  # document was created
    # No task_id in response — import no longer auto-enqueues.
    assert resp.json().get("task_id") is None
    # The ingest queue should be empty for this library.
    db = DatabaseManager.get(str(tmp_library))
    with db.kb_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM ingest_queue").fetchone()[0]
    assert count == 0


def test_library_get_document_file(app_client: TestClient) -> None:
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = resp.json()["document"]["doc_id"]
    resp = app_client.get(f"/api/v1/library/documents/{doc_id}/file")
    assert resp.status_code == 200
    assert resp.content == pdf_bytes

    resp = app_client.head(f"/api/v1/library/documents/{doc_id}/file")
    assert resp.status_code == 200
    assert resp.content == b""
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-length"] == str(len(pdf_bytes))


def test_library_get_document_evidence_reads_requested_sql_page(
    app_client: TestClient, tmp_library: Path
) -> None:
    from mbforge.core.evidence import SourceEvidence
    from mbforge.pipeline.artifacts.evidence_models import (
        DocumentEvidenceArtifact,
        PageFrame,
    )
    from mbforge.storage.source_evidence import persist_source_evidence

    rows = [
        SourceEvidence.create(
            doc_id="doc-evidence",
            page=1,
            bbox=(10, 20, 30, 40),
            raw_text="IC50 < 10 nM",
        ),
        SourceEvidence.create(
            doc_id="doc-evidence",
            page=2,
            bbox=(10, 20, 30, 40),
            raw_text="other page",
        ),
    ]
    persist_source_evidence(
        tmp_library,
        DocumentEvidenceArtifact(
            doc_id="doc-evidence",
            run_id="run-1",
            conventions={"origin": "bottom-left"},
            pages=[
                PageFrame(page=1, width=100, height=100),
                PageFrame(page=2, width=100, height=100),
            ],
            evidence=rows,
        ),
    )

    resp = app_client.get(
        "/api/v1/library/documents/doc-evidence/evidence",
        params={"page": 1},
    )

    assert resp.status_code == 200
    assert [item["raw_text"] for item in resp.json()] == ["IC50 < 10 nM"]
    assert resp.json()[0]["evidence_id"] == rows[0].evidence_id


def test_library_get_document_crop_accepts_absolute_rel_path(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Historical data stores absolute crop paths in image_path; the crop
    endpoint must normalize them to the filename and serve the image."""
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = resp.json()["document"]["doc_id"]

    crops = tmp_library / "storage" / doc_id / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    (crops / "page_0001_mol_0001.png").write_bytes(b"fake png bytes")

    # Canonical relative path still works.
    resp = app_client.get(
        f"/api/v1/library/documents/{doc_id}/crop",
        params={"rel_path": "page_0001_mol_0001.png"},
    )
    assert resp.status_code == 200
    assert resp.content == b"fake png bytes"

    # Absolute path (as stored by older pipelines) is normalized to basename.
    resp = app_client.get(
        f"/api/v1/library/documents/{doc_id}/crop",
        params={"rel_path": str(crops / "page_0001_mol_0001.png")},
    )
    assert resp.status_code == 200
    assert resp.content == b"fake png bytes"


def test_library_get_document_crop_missing_returns_404(
    app_client: TestClient, tmp_library: Path
) -> None:
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = resp.json()["document"]["doc_id"]

    resp = app_client.get(
        f"/api/v1/library/documents/{doc_id}/crop",
        params={"rel_path": "no_such_crop.png"},
    )
    assert resp.status_code == 404

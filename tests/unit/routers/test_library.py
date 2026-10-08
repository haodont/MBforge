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
    from mbforge.foundation import config

    settings_path = tmp_path / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "_SETTINGS_PATH", settings_path)

    root = str(tmp_path / "new_lib")
    resp = app_client.post("/api/v1/library/configure", json={"root": root})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_library_import_and_list(app_client: TestClient, tmp_library: Path) -> None:
    """An import lists the document immediately, resting at ``pending``."""
    from mbforge.service.use_cases.documents.library import LibraryStore

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
    # Import started processing, so it reports the run it created.
    assert data["run_id"]

    # A freshly imported document is visible right away, resting at pending.
    store = LibraryStore.get(str(tmp_library))
    doc = store.get_document(doc_id)
    assert doc is not None
    assert doc.status == "pending"
    assert doc_id in {d.doc_id for d in store.list_documents()}

    # Once the run records an outcome the status reflects it.
    store.update_document_status(doc_id, "ready")
    resp = app_client.post("/api/v1/library/documents", json={})
    assert resp.status_code == 200
    ids = {d["doc_id"] for d in resp.json()["documents"]}
    assert doc_id in ids


def test_library_import_auto_enqueues_processing_run(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Import submits the new document for processing in the same request."""
    from mbforge.db.sqlite.database import DatabaseManager

    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("queued.pdf", b"%PDF-1.4 fake pdf", "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    doc_id = body["document"]["doc_id"]
    assert body["run_id"]

    db = DatabaseManager.get(str(tmp_library))
    with db.kb_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, run_id, status FROM ingest_queue WHERE doc_id = ?",
            (doc_id,),
        ).fetchall()
    # One DAG node per stage, all owned by the run reported to the caller.
    assert rows
    assert {row["run_id"] for row in rows} == {body["run_id"]}


def test_library_import_respects_disabled_auto_enqueue(
    app_client: TestClient, tmp_library: Path, patch_config
) -> None:
    """``ingest.auto_enqueue_on_import = false`` keeps import a register-only step."""
    from mbforge.db.sqlite.database import DatabaseManager

    patch_config(lambda cfg: setattr(cfg.ingest, "auto_enqueue_on_import", False))

    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("manual.pdf", b"%PDF-1.4 fake pdf", "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] is None

    db = DatabaseManager.get(str(tmp_library))
    with db.kb_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM ingest_queue WHERE doc_id = ?",
            (body["document"]["doc_id"],),
        ).fetchone()[0]
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
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence

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
    persist_source_evidence(tmp_library, rows)

    resp = app_client.get(
        "/api/v1/library/documents/doc-evidence/evidence",
        params={"page": 1},
    )

    assert resp.status_code == 200
    assert [item["raw_text"] for item in resp.json()] == ["IC50 < 10 nM"]
    assert resp.json()[0]["evidence_id"] == rows[0].evidence_id


def test_library_get_document_evidence_annotates_patent_paragraphs(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A page-2 row that continues a page-1 paragraph reports that paragraph."""
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence

    rows = [
        SourceEvidence.create(
            doc_id="doc-paragraphs",
            page=1,
            bbox=(10, 700, 300, 720),
            raw_text="[0001] A paragraph that",
        ),
        SourceEvidence.create(
            doc_id="doc-paragraphs",
            page=2,
            bbox=(10, 800, 300, 810),
            raw_text="continues on the next page.",
        ),
        SourceEvidence.create(
            doc_id="doc-paragraphs",
            page=2,
            bbox=(10, 700, 300, 710),
            raw_text="[0002] Another paragraph.",
        ),
        *[
            SourceEvidence.create(
                doc_id="doc-paragraphs",
                page=2,
                bbox=(60, 600 - index * 10, 300, 610 - index * 10),
                raw_text=f"({label}) an indented sub-item",
            )
            for index, label in enumerate(("a", "b", "c"))
        ],
    ]
    persist_source_evidence(tmp_library, rows)

    resp = app_client.get(
        "/api/v1/library/documents/doc-paragraphs/evidence",
        params={"page": 2},
    )

    assert resp.status_code == 200
    continuation, second, first_item, _, last_item = resp.json()
    assert continuation["raw_text"] == "continues on the next page."
    assert continuation["paragraph_number"] == "0001"
    assert continuation["paragraph_start"] is False
    assert continuation["paragraph_id"] != second["paragraph_id"]
    assert second["paragraph_number"] == "0002"
    assert second["paragraph_start"] is True
    # The sub-items join the paragraph above them, on their own indented lines.
    assert first_item["paragraph_id"] == second["paragraph_id"]
    assert first_item["paragraph_line"] == 1
    assert first_item["indent_level"] == 1
    assert last_item["paragraph_line"] == 3
    assert last_item["indent_level"] == 1


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

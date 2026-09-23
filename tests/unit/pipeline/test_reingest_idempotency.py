"""Regression tests for re-ingest idempotency (Phase 1 A2)."""

from __future__ import annotations

import pytest

from mbforge.adapters.persistence.sqlite.database import DatabaseManager
from mbforge.application.use_cases.documents.library import LibraryStore
from mbforge.foundation.layout import LibraryLayout


def test_clear_pipeline_data_removes_molecule_detections(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Re-ingesting a document must not hit UNIQUE constraints on molecule_detections."""
    root = str(tmp_path / "library")
    store = LibraryStore.get(root)
    src = tmp_path / "library_src" / "test.pdf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"%PDF-1.4 dummy")
    doc = store.add_document(str(src), title="test")
    doc_id = doc.doc_id
    db = DatabaseManager.get(root)
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name, source_doc) VALUES (?, ?, ?, ?)",
            ("mol_1", "CCO", "ethanol", doc_id),
        )
        conn.execute(
            """
            INSERT INTO molecule_detections
                (mol_id, doc_id, page, crop_relpath, conf_moldet, conf_molscribe)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("mol_1", doc_id, 1, "crops/x.png", 0.9, 0.8),
        )

    store.clear_pipeline_data(doc_id)

    # Re-inserting the same detection after cleanup must succeed.
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name, source_doc) VALUES (?, ?, ?, ?)",
            ("mol_1", "CCO", "ethanol", doc_id),
        )
        conn.execute(
            """
            INSERT INTO molecule_detections
                (mol_id, doc_id, page, crop_relpath, conf_moldet, conf_molscribe)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("mol_1", doc_id, 1, "crops/x.png", 0.9, 0.8),
        )
        rows = conn.execute(
            "SELECT COUNT(*) FROM molecule_detections WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        assert rows[0][0] == 1


def test_clear_pipeline_data_removes_artifacts(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Re-ingest cleanup must remove stale document Markdown and report.json."""
    root = str(tmp_path / "library")
    store = LibraryStore.get(root)
    src = tmp_path / "library_src" / "test.pdf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"%PDF-1.4 dummy")
    doc = store.add_document(str(src), title="test")
    doc_id = doc.doc_id
    resolver = LibraryLayout(root)
    resolver.storage_dir(doc_id).mkdir(parents=True, exist_ok=True)
    resolver.document_md(doc_id).write_text("# old")
    (resolver.report_json(doc_id)).write_text("{}")
    resolver.pages_dir(doc_id).mkdir(exist_ok=True)
    (resolver.page_text(doc_id, 1)).write_text("old text")

    store.clear_pipeline_data(doc_id)

    assert not resolver.document_md(doc_id).exists()
    assert not resolver.report_json(doc_id).exists()
    assert not resolver.pages_dir(doc_id).exists()

"""Tests for the document library store.

Covers ``services.use_cases.documents.library.LibraryStore``: the add/get/delete
lifecycle (including the missing-source error and the no-leftover-snapshot
guarantee) and the literal-substring listing search.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.foundation.errors import MBForgeError
from mbforge.service.use_cases.documents.library import LibraryStore


def test_document_store_add_get_delete_round_trip(tmp_path: Path) -> None:
    """Adding copies metadata, a missing source raises, deleting removes the doc."""
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf content")
    doc = store.add_document(src, title="My Paper")
    assert doc.doc_id
    assert doc.title == "My Paper"
    retrieved = store.get_document(doc.doc_id)
    assert retrieved is not None
    assert retrieved.title == "My Paper"

    with pytest.raises(MBForgeError):
        store.add_document(tmp_path / "missing.pdf")

    store.delete_documents([doc.doc_id])
    assert store.get_document(doc.doc_id) is None
    assert not (tmp_path / "storage" / doc.doc_id).exists()
    # Deletion leaves no snapshot behind: a batch delete must not pile up
    # one backup per document.
    backups = tmp_path / "backups"
    assert not backups.exists() or not list(backups.iterdir())


def test_delete_documents_clears_ingest_bookkeeping(tmp_path: Path) -> None:
    """A deleted document leaves no queue, run, dependency or log rows."""
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf content")
    doc = store.add_document(src, title="Ingest cleanup")

    db = DatabaseManager.get(str(tmp_path))
    with db.transaction() as kb:
        kb.execute(
            "INSERT INTO ingest_runs (doc_id, run_id) VALUES (?, ?)",
            (doc.doc_id, "run-1"),
        )
        kb.execute(
            "INSERT INTO ingest_stage_deps (doc_id, run_id, stage, depends_on) "
            "VALUES (?, ?, ?, ?)",
            (doc.doc_id, "run-1", "extract", ""),
        )
        kb.execute(
            "INSERT INTO ingest_logs (doc_id, stage, message) VALUES (?, ?, ?)",
            (doc.doc_id, "extract", "seeded"),
        )
        kb.execute(
            "INSERT INTO ingest_queue (id, file_path, doc_id, status) "
            "VALUES (?, ?, ?, ?)",
            ("task-1", "input.pdf", doc.doc_id, "cancelled"),
        )

    store.delete_documents([doc.doc_id])

    with db.transaction() as kb:
        for table in (
            "ingest_runs",
            "ingest_stage_deps",
            "ingest_logs",
            "ingest_queue",
        ):
            count = kb.execute(
                f"SELECT COUNT(*) FROM {table} WHERE doc_id = ?", (doc.doc_id,)
            ).fetchone()[0]
            assert count == 0
        assert (
            kb.execute(
                "SELECT COUNT(*) FROM documents WHERE doc_id = ?", (doc.doc_id,)
            ).fetchone()[0]
            == 0
        )


def test_search_documents_matches_literal_substring(tmp_path: Path) -> None:
    """Search matches literal substrings in title and file_name.

    Search reads the same listing as the workspace, so a document has to have
    a processing outcome before it can be found.
    """
    store = LibraryStore.get(tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    def upload(name: str, content: bytes, title: str) -> None:
        src = src_dir / name
        src.write_bytes(content)
        doc = store.add_uploaded_file_from_path(src, name, title)
        store.update_document_status(doc.doc_id, "ready")

    upload("a.pdf", b"a", "100% solution")
    upload("b.pdf", b"b", "100 percent solution")
    assert len(store.list_documents()) == 2

    matches = store.search_documents("100%")
    assert len(matches) == 1
    assert matches[0].title == "100% solution"

    matches = store.search_documents("Alpha")
    assert len(matches) == 0
    upload("c.pdf", b"c", "Alpha Paper")
    matches = store.search_documents("Alpha")
    assert len(matches) == 1
    assert matches[0].title == "Alpha Paper"

    matches = store.search_documents("100_")
    assert len(matches) == 0

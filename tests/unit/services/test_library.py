from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.foundation.errors import MBForgeError
from mbforge.service.use_cases.documents.library import LibraryStore


def test_add_document_and_get(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf content")
    doc = store.add_document(src, title="My Paper")
    assert doc.doc_id
    assert doc.title == "My Paper"
    retrieved = store.get_document(doc.doc_id)
    assert retrieved is not None
    assert retrieved.title == "My Paper"


def test_add_document_missing_file(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    with pytest.raises(MBForgeError):
        store.add_document(tmp_path / "missing.pdf")


def test_delete_document(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf")
    doc = store.add_document(src)
    store.delete_documents([doc.doc_id])
    assert store.get_document(doc.doc_id) is None
    assert not (tmp_path / "storage" / doc.doc_id).exists()
    # Deletion leaves no snapshot behind: a batch delete must not pile up
    # one backup per document.
    backups = tmp_path / "backups"
    assert not backups.exists() or not list(backups.iterdir())


def test_search_documents_substring(tmp_path: Path) -> None:
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

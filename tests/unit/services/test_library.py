from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.services.documents.library import LibraryStore
from mbforge.utils.errors import MBForgeError


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
    store.delete_document(doc.doc_id)
    assert store.get_document(doc.doc_id) is None
    backups = list((tmp_path / ".mbforge" / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "storage" / doc.doc_id / "input.pdf").read_bytes() == b"pdf"
    assert (backups[0] / "library.db").is_file()


def test_search_documents_substring(tmp_path: Path) -> None:
    """Search matches literal substrings in title and file_name."""
    store = LibraryStore.get(tmp_path)
    store.add_uploaded_file(b"a", "a.pdf", title="100% solution")
    store.add_uploaded_file(b"b", "b.pdf", title="100 percent solution")
    assert len(store.list_documents()) == 2

    matches = store.search_documents("100%")
    assert len(matches) == 1
    assert matches[0].title == "100% solution"

    matches = store.search_documents("Alpha")
    assert len(matches) == 0
    store.add_uploaded_file(b"c", "c.pdf", title="Alpha Paper")
    matches = store.search_documents("Alpha")
    assert len(matches) == 1
    assert matches[0].title == "Alpha Paper"

    matches = store.search_documents("100_")
    assert len(matches) == 0

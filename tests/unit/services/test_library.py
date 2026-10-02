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
    store.delete_document(doc.doc_id)
    assert store.get_document(doc.doc_id) is None
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "storage" / doc.doc_id / "input.pdf").read_bytes() == b"pdf"
    assert (backups[0] / "database.json").is_file()


def test_search_documents_substring(tmp_path: Path) -> None:
    """Search matches literal substrings in title and file_name."""
    store = LibraryStore.get(tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    def upload(name: str, content: bytes, title: str) -> None:
        src = src_dir / name
        src.write_bytes(content)
        store.add_uploaded_file_from_path(src, name, title)

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

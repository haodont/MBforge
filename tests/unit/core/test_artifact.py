"""Unit tests for LibraryLayout document-level path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.storage.layout import InvalidDocIdError, LibraryLayout
from mbforge.utils.errors import PathTraversalError


def test_image_resolves_valid_filename_in_images_dir(tmp_path: Path) -> None:
    resolver = LibraryLayout(tmp_path)
    assert resolver.images_dir("doc123") == tmp_path / "storage" / "doc123" / "images"
    assert (
        resolver.image("doc123", "abc.jpg")
        == tmp_path / "storage" / "doc123" / "images" / "abc.jpg"
    )


def test_image_rejects_empty_filename(tmp_path: Path) -> None:
    resolver = LibraryLayout(tmp_path)
    with pytest.raises(PathTraversalError):
        resolver.image("doc123", "")


def test_image_rejects_path_separator(tmp_path: Path) -> None:
    resolver = LibraryLayout(tmp_path)
    with pytest.raises(PathTraversalError):
        resolver.image("doc123", "foo/bar.jpg")
    with pytest.raises(PathTraversalError):
        resolver.image("doc123", "foo\\bar.jpg")


@pytest.mark.parametrize("filename", ["../etc/passwd", "foo/../bar.jpg"])
def test_image_rejects_dotdot(tmp_path: Path, filename: str) -> None:
    resolver = LibraryLayout(tmp_path)
    with pytest.raises(PathTraversalError):
        resolver.image("doc123", filename)


def test_storage_dir_rejects_invalid_doc_id(tmp_path: Path) -> None:
    resolver = LibraryLayout(tmp_path)
    with pytest.raises(InvalidDocIdError):
        resolver.storage_dir("doc/with/slash")

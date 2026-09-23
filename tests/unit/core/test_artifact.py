"""Unit tests for LibraryLayout document-level path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.foundation.layout import InvalidDocIdError, LibraryLayout


def test_storage_dir_rejects_invalid_doc_id(tmp_path: Path) -> None:
    resolver = LibraryLayout(tmp_path)
    with pytest.raises(InvalidDocIdError):
        resolver.storage_dir("doc/with/slash")

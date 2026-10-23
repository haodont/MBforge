"""Unit tests for :mod:`mbforge.foundation.file_scanner`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mbforge.foundation.file_scanner import (
    build_file_tree,
    scan_library_files,
)


def test_scan_library_files_filters_extensions_and_skips_hidden_dirs(
    tmp_path: Path,
) -> None:
    """Non-recursive scans list only supported extensions; recursive scans
    descend into subdirectories but skip hidden and node_modules dirs, and a
    missing root yields an empty list."""
    (tmp_path / "a.pdf").write_text("pdf")
    (tmp_path / "b.md").write_text("md")
    (tmp_path / "ignored.exe").write_text("exe")
    assert scan_library_files(tmp_path, recursive=False) == ["a.pdf", "b.md"]

    nested = tmp_path / "subdir"
    nested.mkdir()
    (nested / "inner.txt").write_text("txt")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.pdf").write_text("pdf")
    skip = tmp_path / "node_modules"
    skip.mkdir()
    (skip / "bad.pdf").write_text("pdf")

    result = scan_library_files(tmp_path, recursive=True)
    assert "a.pdf" in result
    assert "subdir/inner.txt" in result
    assert not any(r.startswith(".hidden") for r in result)
    assert not any("node_modules" in r for r in result)
    assert scan_library_files(tmp_path / "does_not_exist", recursive=True) == []


def test_build_file_tree_lists_files_and_logs_permission_errors(tmp_path: Path) -> None:
    """The tree lists files and nested children, returns [] for empty/missing
    roots, and logs a permission error instead of swallowing it silently."""
    (tmp_path / "paper.pdf").write_text("pdf")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("md")

    tree = build_file_tree(tmp_path)
    names = {n.name for n in tree}
    assert "paper.pdf" in names
    doc_node = next((n for n in tree if n.name == "docs"), None)
    assert doc_node is not None
    assert any(c.name == "notes.md" for c in doc_node.children)

    empty = tmp_path / "empty"
    empty.mkdir()
    assert build_file_tree(empty) == []
    assert build_file_tree(tmp_path / "missing") == []

    from mbforge.foundation import file_scanner

    with (
        patch.object(file_scanner, "logger") as mock_logger,
        patch.object(Path, "iterdir", side_effect=PermissionError("denied")),
    ):
        assert build_file_tree(tmp_path) == []
    mock_logger.warning.assert_called_once()
    assert "Permission denied" in mock_logger.warning.call_args[0][0]

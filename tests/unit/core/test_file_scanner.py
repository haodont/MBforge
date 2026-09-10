from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mbforge.utils.file_scanner import (
    build_file_tree,
    scan_library_files,
)


def test_scan_library_files_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_text("pdf")
    (tmp_path / "b.md").write_text("md")
    (tmp_path / "ignored.exe").write_text("exe")
    result = scan_library_files(tmp_path, recursive=False)
    assert result == ["a.pdf", "b.md"]


def test_scan_library_files_recursive_skips_hidden_and_skip_dirs(
    tmp_path: Path,
) -> None:
    (tmp_path / "doc.pdf").write_text("pdf")
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
    assert "doc.pdf" in result
    assert "subdir/inner.txt" in result
    assert not any(r.startswith(".hidden") for r in result)
    assert not any("node_modules" in r for r in result)
    assert scan_library_files(tmp_path / "does_not_exist", recursive=True) == []


def test_build_file_tree(tmp_path: Path) -> None:
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


def test_build_file_tree_logs_permission_warning(tmp_path: Path) -> None:
    """Permission errors during tree walk must be logged, not swallowed silently."""
    from mbforge.utils import file_scanner

    with (
        patch.object(file_scanner, "logger") as mock_logger,
        patch.object(Path, "iterdir", side_effect=PermissionError("denied")),
    ):
        result = build_file_tree(tmp_path)

    assert result == []
    mock_logger.warning.assert_called_once()
    assert "Permission denied" in mock_logger.warning.call_args[0][0]

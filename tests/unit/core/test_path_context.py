from __future__ import annotations

from types import SimpleNamespace

import pytest

from mbforge.foundation.layout import (
    LibraryLayout,
    LibraryPathContext,
    canonicalize_library_root,
    resolve_library_root,
)


def test_library_root_is_canonicalized_before_configured_comparison(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "library"
    configured = SimpleNamespace(library_root=str(root))
    monkeypatch.setattr(
        "mbforge.foundation.layout.load_global_config", lambda: configured
    )

    resolved = resolve_library_root(str(root / ".." / root.name))

    assert resolved == root.resolve()
    assert canonicalize_library_root(root) == root.resolve()

    context = LibraryPathContext.from_request({"library_root": str(root)})
    assert context.root == root.resolve()
    assert context.layout.library_root == context.root


def test_library_layout_rejects_traversal_in_relative_paths(tmp_path) -> None:
    layout = LibraryLayout(tmp_path / "library")

    with pytest.raises(ValueError):
        layout.resolve_relative_path("storage/../outside.pdf")

"""Path contracts for ``mbforge.foundation.layout``.

Merges the former ``test_path_context`` / ``test_path_utils`` / ``test_artifact``
modules: library-root resolution against the configured root, canonicalisation,
and the traversal / doc-id rejection that guards every library path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mbforge.foundation.layout import (
    InvalidDocIdError,
    InvalidPathError,
    LibraryLayout,
    LibraryPathContext,
    canonicalize_library_root,
    resolve_library_root,
)


def _configure(monkeypatch: pytest.MonkeyPatch, library_root: str) -> None:
    monkeypatch.setattr(
        "mbforge.foundation.layout.load_global_config",
        lambda: SimpleNamespace(library_root=library_root),
    )


def test_resolve_library_root_requires_a_configured_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No configured root and no explicit value is an error, not a fallback."""
    _configure(monkeypatch, "")
    with pytest.raises(InvalidPathError):
        resolve_library_root(None)


def test_resolve_library_root_rejects_unsafe_or_mismatched_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Relative paths, traversal escapes and roots outside the configured
    library are all refused."""
    _configure(monkeypatch, "C:/configured")
    for value in ["relative", "C:/configured/../other"]:
        with pytest.raises(InvalidPathError):
            resolve_library_root(value)

    configured = tmp_path / "configured"
    other = tmp_path / "other"
    _configure(monkeypatch, str(configured))
    with pytest.raises(InvalidPathError):
        resolve_library_root(str(other))


def test_library_root_is_canonicalized_and_traversal_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A matching root canonicalises (``..`` folded) before comparison, the
    request context adopts the canonical root, and relative paths may not
    escape the library or smuggle a doc_id through a separator."""
    root = tmp_path / "library"
    _configure(monkeypatch, str(root))

    resolved = resolve_library_root(str(root / ".." / root.name))
    assert resolved == root.resolve()
    assert canonicalize_library_root(root) == root.resolve()

    context = LibraryPathContext.from_request({"library_root": str(root)})
    assert context.root == root.resolve()
    assert context.layout.library_root == context.root

    layout = LibraryLayout(root)
    with pytest.raises(ValueError):
        layout.resolve_relative_path("storage/../outside.pdf")
    with pytest.raises(InvalidDocIdError):
        layout.storage_dir("doc/with/slash")

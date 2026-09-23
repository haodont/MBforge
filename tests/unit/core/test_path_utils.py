from __future__ import annotations

import pytest

from mbforge.foundation.layout import InvalidPathError, resolve_library_root


def test_resolve_library_root_requires_configured_root(monkeypatch):
    monkeypatch.setattr(
        "mbforge.foundation.layout.load_global_config",
        lambda: type("C", (), {"library_root": ""})(),
    )
    with pytest.raises(InvalidPathError):
        resolve_library_root(None)


@pytest.mark.parametrize("value", ["relative", "C:/configured/../other"])
def test_resolve_library_root_rejects_unsafe(monkeypatch, value):
    monkeypatch.setattr(
        "mbforge.foundation.config.load_global_config",
        lambda: type("C", (), {"library_root": "C:/configured"})(),
    )
    with pytest.raises(InvalidPathError):
        resolve_library_root(value)


def test_resolve_library_root_rejects_mismatch(monkeypatch, tmp_path):
    configured = tmp_path / "configured"
    other = tmp_path / "other"
    monkeypatch.setattr(
        "mbforge.foundation.config.load_global_config",
        lambda: type("C", (), {"library_root": str(configured)})(),
    )
    with pytest.raises(InvalidPathError):
        resolve_library_root(str(other))

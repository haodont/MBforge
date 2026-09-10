"""Dual-channel model download: ModelScope first, HuggingFace fallback."""

from __future__ import annotations

from pathlib import Path

from mbforge.infra import resource_manager as rm
from mbforge.infra.resource_manager import ResourceManager, ResourceStatus

_FILES = ("moldet_v2_yolo26n_960_doc.pt", "moldet_v2_yolo26n_640_general.pt")


def _no_bundled_assets(monkeypatch, tmp_path: Path) -> None:
    """Hide project-bundled weights so these tests exercise the download path."""
    # String form avoids importing model_locator directly (circular import
    # with resource_manager during collection); resource_manager already
    # imports model_locator at module load, so the attribute is resolvable.
    monkeypatch.setattr(
        "mbforge.infra.model_locator._project_assets_dir",
        lambda: tmp_path / "no-assets",
    )


def _fake_cache(tmp_path: Path) -> Path:
    """Write the catalog's moldet weight files under the snapshot dir."""
    dest = tmp_path / "MolDetv2"
    dest.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        (dest / name).write_bytes(b"weights")
    return dest


def test_ensure_falls_back_to_hf_when_modelscope_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """MS channel returning False must trigger the HuggingFace fallback."""
    _no_bundled_assets(monkeypatch, tmp_path)
    monkeypatch.setattr(
        rm,
        "_download_model_from_modelscope",
        lambda info, callback: False,
    )
    hf_calls: dict[str, int] = {"n": 0}

    def _fake_hf(info, callback) -> bool:
        hf_calls["n"] += 1
        _fake_cache(tmp_path)
        return True

    monkeypatch.setattr(rm, "_download_model_from_hf", _fake_hf)
    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)

    result = ResourceManager.ensure("moldet")
    assert hf_calls["n"] == 1
    assert result.status == ResourceStatus.READY
    assert result.local_path


def test_ensure_uses_modelscope_first_when_it_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    """A successful ModelScope download must not call the HF channel."""
    _no_bundled_assets(monkeypatch, tmp_path)
    ms_calls: dict[str, int] = {"n": 0}

    def _fake_ms(info, callback) -> bool:
        ms_calls["n"] += 1
        _fake_cache(tmp_path)
        return True

    monkeypatch.setattr(rm, "_download_model_from_modelscope", _fake_ms)
    monkeypatch.setattr(
        rm,
        "_download_model_from_hf",
        lambda info, callback: (_ for _ in ()).throw(AssertionError("HF must not run")),
    )
    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)

    result = ResourceManager.ensure("moldet")
    assert ms_calls["n"] == 1
    assert result.status == ResourceStatus.READY


def test_ensure_fails_when_both_channels_fail(monkeypatch, tmp_path: Path) -> None:
    """When MS and HF both fail, ensure reports not_found (no crash)."""
    _no_bundled_assets(monkeypatch, tmp_path)
    monkeypatch.setattr(
        rm,
        "_download_model_from_modelscope",
        lambda info, callback: False,
    )
    monkeypatch.setattr(
        rm,
        "_download_model_from_hf",
        lambda info, callback: False,
    )
    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)

    result = ResourceManager.ensure("moldet")
    assert result.status == ResourceStatus.NOT_FOUND

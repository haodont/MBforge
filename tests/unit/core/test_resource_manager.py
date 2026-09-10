"""Tests for resource catalog integrity verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mbforge.infra.resource_manager import (
    RESOURCE_CATALOG,
    ResourceInfo,
    ResourceManager,
    ResourceStatus,
    ResourceType,
    _check_model_file,
    _check_model_snapshot,
    _verify_model_path,
)


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_verify_model_path_file_matching(tmp_path: Path) -> None:
    data = b"hello model"
    f = tmp_path / "model.pth"
    f.write_bytes(data)
    info = ResourceInfo(
        id="test",
        name="Test",
        type=ResourceType.MODEL,
        description="",
        sha256=_sha256_of_bytes(data),
        expected_size=len(data),
    )
    assert _verify_model_path(f, info) is True


def test_verify_model_path_file_hash_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "model.pth"
    f.write_bytes(b"good data")
    info = ResourceInfo(
        id="test",
        name="Test",
        type=ResourceType.MODEL,
        description="",
        sha256="0" * 64,
        expected_size=f.stat().st_size,
    )
    assert _verify_model_path(f, info) is False


def test_verify_model_path_file_size_mismatch(tmp_path: Path) -> None:
    data = b"exact data"
    f = tmp_path / "model.pth"
    f.write_bytes(data)
    info = ResourceInfo(
        id="test",
        name="Test",
        type=ResourceType.MODEL,
        description="",
        expected_size=len(data) + 1,
    )
    assert _verify_model_path(f, info) is False


def test_verify_model_path_no_checksum_skips(tmp_path: Path) -> None:
    f = tmp_path / "model.pth"
    f.write_bytes(b"anything")
    info = ResourceInfo(
        id="test",
        name="Test",
        type=ResourceType.MODEL,
        description="",
    )
    assert _verify_model_path(f, info) is True


def test_verify_model_path_snapshot_single_file(tmp_path: Path) -> None:
    data = b"snapshot weights"
    dest = tmp_path / "MolParser"
    dest.mkdir()
    weight = dest / "model.pth"
    weight.write_bytes(data)
    info = ResourceInfo(
        id="molparser",
        name="MolParser",
        type=ResourceType.MODEL,
        description="",
        files=["model.pth"],
        sha256=_sha256_of_bytes(data),
        expected_size=len(data),
    )
    assert _verify_model_path(dest, info) is True


def test_verify_model_path_snapshot_missing_file(tmp_path: Path) -> None:
    dest = tmp_path / "MolParser"
    dest.mkdir()
    info = ResourceInfo(
        id="molparser",
        name="MolParser",
        type=ResourceType.MODEL,
        description="",
        files=["missing.pth"],
        sha256="0" * 64,
        expected_size=1,
    )
    assert _verify_model_path(dest, info) is False


def test_check_model_file_flags_size_mismatch(tmp_path: Path) -> None:
    """_check_model_file should report PARTIAL when the found file size differs."""
    repo_dir = tmp_path / "MolParser"
    repo_dir.mkdir()
    weight = repo_dir / "model.pth"
    weight.write_bytes(b"short")
    info = ResourceInfo(
        id="molparser",
        name="MolParser",
        type=ResourceType.MODEL,
        description="",
        download_type="file",
        local_name="model.pth",
        expected_size=1000,
    )
    # Temporarily point the MBForge cache dir to our tmp_path via monkeypatching
    import mbforge.infra.resource_manager as rm

    original_get_model_cache_dir = rm._get_model_cache_dir
    try:
        rm._get_model_cache_dir = lambda: tmp_path
        result = _check_model_file(info)
        assert result.status == ResourceStatus.PARTIAL, result
        assert "大小" in result.error or "size" in result.error.lower()
    finally:
        rm._get_model_cache_dir = original_get_model_cache_dir


def test_check_model_snapshot_flags_size_mismatch(tmp_path: Path) -> None:
    """_check_model_snapshot should report PARTIAL when directory size differs."""
    repo_dir = tmp_path / "MolParser-Mobile"
    repo_dir.mkdir()
    weight = repo_dir / "model.pth"
    weight.write_bytes(b"short")
    info = ResourceInfo(
        id="molparser",
        name="MolParser",
        type=ResourceType.MODEL,
        description="",
        ms_repo="UniParser/MolParser-Mobile",
        download_type="snapshot",
        local_name="MolParser-Mobile",
        files=["model.pth"],
        expected_size=1000,
    )
    import mbforge.infra.resource_manager as rm

    original_get_model_cache_dir = rm._get_model_cache_dir
    try:
        rm._get_model_cache_dir = lambda: tmp_path
        result = _check_model_snapshot(info)
        assert result.status == ResourceStatus.PARTIAL, result
        assert "大小" in result.error or "size" in result.error.lower()
    finally:
        rm._get_model_cache_dir = original_get_model_cache_dir


def test_check_model_snapshot_ignores_sidecar_file_sizes(tmp_path: Path) -> None:
    """Snapshot metadata must not make a valid primary weight look partial."""
    repo_dir = tmp_path / "MolParser"
    repo_dir.mkdir()
    weight = repo_dir / "model.pth"
    weight.write_bytes(b"valid weights")
    (repo_dir / ".msc").write_text("metadata", encoding="utf-8")
    info = ResourceInfo(
        id="molparser",
        name="MolParser",
        type=ResourceType.MODEL,
        description="",
        ms_repo="UniParser/MolParser-Mobile",
        download_type="snapshot",
        local_name="MolParser",
        files=["model.pth"],
        expected_size=weight.stat().st_size,
    )
    import mbforge.infra.resource_manager as rm

    original_get_model_cache_dir = rm._get_model_cache_dir
    try:
        rm._get_model_cache_dir = lambda: tmp_path
        result = _check_model_snapshot(info)
        assert result.status == ResourceStatus.READY, result
    finally:
        rm._get_model_cache_dir = original_get_model_cache_dir


def test_molparser_catalog_has_weight_files() -> None:
    """The MolParser entry must list the recognizer weight + config files."""
    info = RESOURCE_CATALOG["molparser"]
    assert "model.safetensors" in info.files
    assert info.ms_repo == "UniParser/MolParser-Mobile"
    assert info.hf_repo == "UniParser/MolParser-Mobile"


def test_moldet_catalog_has_yolo26_weights() -> None:
    """The moldet entry must point at the MolDetv2-YOLO26 repo with .pt weights."""
    info = RESOURCE_CATALOG["moldet"]
    assert "moldet_v2_yolo26n_960_doc.pt" in info.files
    assert "moldet_v2_yolo26n_640_general.pt" in info.files
    assert info.ms_repo == "UniParser/MolDetv2-YOLO26"


def test_none_info_is_handled(tmp_path: Path) -> None:
    """None ResourceInfo must not crash the checkers and must verify as False."""
    assert _check_model_file(None).status == ResourceStatus.ERROR  # type: ignore[arg-type]
    assert _check_model_snapshot(None).status == ResourceStatus.ERROR  # type: ignore[arg-type]
    f = tmp_path / "x.pth"
    f.write_bytes(b"x")
    assert _verify_model_path(f, None) is False  # type: ignore[arg-type]


def test_bundled_asset_takes_precedence_over_downloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A project-bundled weight makes the model READY without a download."""
    import mbforge.infra.model_locator as ml

    asset = tmp_path / "moldetv2_structure_ft.pt"
    asset.write_bytes(b"fake weights")
    monkeypatch.setattr(ml, "_project_assets_dir", lambda: tmp_path)

    moldet = RESOURCE_CATALOG["moldet"]
    assert ml.bundled_model_asset(moldet) == asset
    result = _check_model_snapshot(moldet)
    assert result.status == ResourceStatus.READY
    assert Path(result.local_path) == asset

    # Non-matching resources are untouched (no accidental hijack).
    molparser = RESOURCE_CATALOG["molparser"]
    assert ml.bundled_model_asset(molparser) is None


def test_resolve_model_for_backend_returns_bundled_single_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """resolve_model_for_backend returns the bundled file even when the
    catalog subpath does not exist under the asset directory."""
    import mbforge.infra.model_locator as ml

    asset = tmp_path / "moldetv2_structure_ft.pt"
    asset.write_bytes(b"fake weights")
    monkeypatch.setattr(ml, "_project_assets_dir", lambda: tmp_path)

    resolved = ResourceManager.resolve_model_for_backend(
        "moldet", subpath="moldet_v2_yolo26n_960_doc.pt"
    )
    assert resolved == asset

"""Tests for resource catalog integrity verification.

Covers ``mbforge.server.resource_manager`` (``_verify_model_path``, the catalog)
and ``mbforge.server.models.assets.locator`` (``_check_model_file`` /
``_check_model_snapshot``): hash/size verification, snapshot handling, cache-dir
scoping and catalog metadata.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mbforge.server.models.assets.locator import (
    _check_model_file,
    _check_model_snapshot,
)
from mbforge.server.resource_manager import (
    RESOURCE_CATALOG,
    ResourceInfo,
    ResourceStatus,
    ResourceType,
    _verify_model_path,
)


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _info(**overrides) -> ResourceInfo:
    base = {
        "id": "test",
        "name": "Test",
        "type": ResourceType.MODEL,
        "description": "",
    }
    base.update(overrides)
    return ResourceInfo(**base)


def test_verify_model_path_checks_hash_size_and_presence(tmp_path: Path) -> None:
    """``_verify_model_path`` accepts a matching file/snapshot, rejects a hash
    or size mismatch and a missing snapshot member, and skips when no checksum
    is declared."""
    data = b"hello model"
    f = tmp_path / "model.pth"
    f.write_bytes(data)
    assert (
        _verify_model_path(
            f, _info(sha256=_sha256_of_bytes(data), expected_size=len(data))
        )
        is True
    )

    other = tmp_path / "other.pth"
    other.write_bytes(b"good data")
    assert (
        _verify_model_path(
            other, _info(sha256="0" * 64, expected_size=other.stat().st_size)
        )
        is False
    )

    sized = tmp_path / "sized.pth"
    sized.write_bytes(b"exact data")
    assert (
        _verify_model_path(sized, _info(expected_size=len(b"exact data") + 1)) is False
    )

    unchecked = tmp_path / "unchecked.pth"
    unchecked.write_bytes(b"anything")
    assert _verify_model_path(unchecked, _info()) is True

    snapshot = tmp_path / "MolParser"
    snapshot.mkdir()
    weight = snapshot / "model.pth"
    weight.write_bytes(data)
    assert (
        _verify_model_path(
            snapshot,
            _info(
                id="molparser",
                files=["model.pth"],
                sha256=_sha256_of_bytes(data),
                expected_size=len(data),
            ),
        )
        is True
    )

    missing = tmp_path / "MolParser-missing"
    missing.mkdir()
    assert (
        _verify_model_path(
            missing,
            _info(files=["missing.pth"], sha256="0" * 64, expected_size=1),
        )
        is False
    )


def test_check_model_flags_size_mismatch(tmp_path: Path, monkeypatch) -> None:
    """``_check_model_file``/``_check_model_snapshot`` report PARTIAL when the
    found file or directory size differs from the catalog."""
    import mbforge.server.resource_manager as rm

    repo_dir = tmp_path / "MolParser"
    repo_dir.mkdir()
    (repo_dir / "model.pth").write_bytes(b"short")
    file_info = _info(
        id="molparser",
        # The weights live in the repo-named subdirectory, so the probe needs
        # ``ms_repo`` to recognise it — without it the subdirectory name is
        # not a candidate at all.
        ms_repo="UniParser/MolParser",
        download_type="file",
        local_name="model.pth",
        expected_size=1000,
    )

    snap_dir = tmp_path / "MolParser-Mobile"
    snap_dir.mkdir()
    (snap_dir / "model.pth").write_bytes(b"short")
    snapshot_info = _info(
        id="molparser",
        ms_repo="UniParser/MolParser-Mobile",
        download_type="snapshot",
        local_name="MolParser-Mobile",
        files=["model.pth"],
        expected_size=1000,
    )

    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)
    for info, checked in (
        (file_info, _check_model_file),
        (snapshot_info, _check_model_snapshot),
    ):
        result = checked(info)
        assert result.status == ResourceStatus.PARTIAL, (info.download_type, result)
        assert "大小" in result.error or "size" in result.error.lower()


def test_check_model_snapshot_ignores_sidecar_file_sizes(
    tmp_path: Path, monkeypatch
) -> None:
    """Snapshot metadata must not make a valid primary weight look partial."""
    import mbforge.server.resource_manager as rm

    repo_dir = tmp_path / "MolParser-sidecar"
    repo_dir.mkdir()
    weight = repo_dir / "model.pth"
    weight.write_bytes(b"valid weights")
    (repo_dir / ".msc").write_text("metadata", encoding="utf-8")
    info = _info(
        id="molparser",
        ms_repo="UniParser/MolParser-Mobile",
        download_type="snapshot",
        local_name="MolParser-sidecar",
        files=["model.pth"],
        expected_size=weight.stat().st_size,
    )

    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)
    result = _check_model_snapshot(info)
    assert result.status == ResourceStatus.READY, result


def test_catalog_entries_list_expected_weights() -> None:
    """The MolParser and moldet entries carry the recognizer/detector weight
    files and repos the downloader fetches."""
    molparser = RESOURCE_CATALOG["molparser"]
    assert "model.safetensors" in molparser.files
    assert molparser.ms_repo == "UniParser/MolParser-Mobile"
    assert molparser.hf_repo == "UniParser/MolParser-Mobile"

    moldet = RESOURCE_CATALOG["moldet"]
    assert "moldet_v2_yolo26n_960_doc.pt" in moldet.files
    assert "moldet_v2_yolo26n_640_general.pt" in moldet.files
    assert moldet.ms_repo == "UniParser/MolDetv2-YOLO26"


def test_status_checkers_tolerate_none_and_ignore_stray_weights(
    tmp_path: Path, monkeypatch
) -> None:
    """A None ResourceInfo verifies as False / ERROR instead of crashing, and
    only the model cache directory counts as "downloaded".

    Weights left by other tools (assets/models, a repo-root models/ dir, the
    global HF/ModelScope caches) must not make a model report READY: the cache
    directory is both the download target and the single read source, so a
    ready status always means the app can load the model straight from there.
    """
    import mbforge.server.resource_manager as rm

    assert _check_model_file(None).status == ResourceStatus.ERROR  # type: ignore[arg-type]
    assert _check_model_snapshot(None).status == ResourceStatus.ERROR  # type: ignore[arg-type]
    f = tmp_path / "x.pth"
    f.write_bytes(b"x")
    assert _verify_model_path(f, None) is False  # type: ignore[arg-type]

    cache = tmp_path / "cache"
    cache.mkdir()
    stray = tmp_path / "assets" / "models"
    stray.mkdir(parents=True)
    (stray / "moldetv2_structure_ft.pt").write_bytes(b"stray weights")
    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: cache)

    moldet = RESOURCE_CATALOG["moldet"]
    assert _check_model_snapshot(moldet).status == ResourceStatus.NOT_FOUND

    # Placing the catalog files in the cache directory makes it READY.
    dest = cache / moldet.local_name
    dest.mkdir(parents=True)
    for name in moldet.files:
        (dest / name).write_bytes(b"weights")
    result = _check_model_snapshot(moldet)
    assert result.status == ResourceStatus.READY
    assert Path(result.local_path) == dest

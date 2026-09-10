"""Model cache discovery.

Scans the configured MBForge cache directory and the standard HuggingFace,
ModelScope, and Torch home caches to locate already-downloaded model weights.
This module contains only read-only filesystem probes; downloads live in
``model_downloader.py`` and the public facade remains ``resource_manager.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

from mbforge.utils.logger import get_logger

from .resource_types import (
    ResourceInfo,
    ResourceStatus,
    ResourceStatusResult,
    ResourceType,
)

logger = get_logger(__name__)


def _result(
    info: ResourceInfo,
    status: ResourceStatus,
    local_path: Path | str = "",
    size_mb: float = 0,
    error: str = "",
) -> ResourceStatusResult:
    """Build a ``ResourceStatusResult`` for ``info``."""
    return ResourceStatusResult(
        id=info.id,
        name=info.name,
        type=info.type,
        status=status,
        local_path=str(local_path) if local_path else "",
        size_mb=size_mb,
        error=error,
    )


def _unknown_info_result() -> ResourceStatusResult:
    """Error result used when ``ResourceInfo`` is missing."""
    return ResourceStatusResult(
        id="unknown",
        name="unknown",
        type=ResourceType.MODEL,
        status=ResourceStatus.ERROR,
        error="ResourceInfo is None",
    )


def _project_assets_dir() -> Path | None:
    """Locate the repository assets/models directory, if present.

    The project ships optional model weights under assets/models so
    common models work out of the box without a download. Returns None
    in packaged/runtime environments where the directory is absent.
    """
    candidates = [
        Path.cwd() / "assets" / "models",
        Path(__file__).resolve().parents[3] / "assets" / "models",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def bundled_model_asset(info: ResourceInfo | None) -> Path | None:
    """Return a project-bundled weight file matching ``info``, if any.

    Bundled weights take precedence over downloads (see _check_model_snapshot),
    letting users run key models without pulling files from ModelScope/HF.
    A weight matches when its filename contains the resource id, local name,
    or repository name.
    """
    if info is None:
        return None
    assets = _project_assets_dir()
    if assets is None or not assets.is_dir():
        return None
    names = [
        info.local_name,
        info.id,
        info.ms_repo.split("/")[-1] if info.ms_repo else "",
    ]
    names = [n.lower() for n in names if n]
    for f in sorted(assets.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (
            ".pt",
            ".pth",
            ".safetensors",
            ".bin",
        ):
            continue
        fname = f.name.lower()
        if any(n in fname for n in names):
            return f
    return None


def _file_result(path: Path, info: ResourceInfo) -> ResourceStatusResult:
    """Return READY/PARTIAL for a single weight file."""
    size = path.stat().st_size
    size_mb = round(size / 1024 / 1024, 1)
    if info.expected_size > 0 and size != info.expected_size:
        return _result(
            info,
            ResourceStatus.PARTIAL,
            path,
            size_mb,
            "模型文件大小与期望不符，建议重新下载",
        )
    return _result(info, ResourceStatus.READY, path, size_mb)


def _snapshot_result(path: Path, info: ResourceInfo) -> ResourceStatusResult:
    """Return READY/PARTIAL for a snapshot-style model directory."""
    from . import resource_manager as _rm

    size_mb = _rm._dir_size(path)
    if not _snapshot_has_files(path, info):
        return _result(
            info,
            ResourceStatus.NOT_FOUND,
            path,
            size_mb,
            "目录缺少 catalog 指定的权重文件",
        )
    if not _rm._matches_expected_size(path, info):
        return _result(
            info,
            ResourceStatus.PARTIAL,
            path,
            size_mb,
            "模型文件大小与期望不符，建议重新下载",
        )
    return _result(info, ResourceStatus.READY, path, size_mb)


def _snapshot_has_files(path: Path, info: ResourceInfo) -> bool:
    """目录是否包含 catalog ``info.files`` 指定的全部文件（无 files 则只看权重）."""
    if not info.files:
        return True
    return all((path / f).is_file() for f in info.files)


def _search_in(base: Path, info: ResourceInfo) -> ResourceStatusResult | None:
    """Search ``base`` for an exact file or a subdirectory containing weights."""
    if not base.exists():
        return None

    local_name = info.local_name or f"{info.id}.pt"

    # 1. base/<local_name>（精确文件）
    path = base / local_name
    if path.is_file() and path.stat().st_size > 0:
        return _file_result(path, info)

    # 2. base/<repo_name>/（MBForge 子目录布局）
    repo_name = info.ms_repo.split("/")[-1]
    for subdir_name in [repo_name, local_name, info.id]:
        subdir = base / subdir_name
        if subdir.is_dir():
            for f in subdir.iterdir():
                if f.is_file() and f.suffix in (".pt", ".pth", ".bin", ".safetensors"):
                    return _file_result(f, info)

    # 3. base/ 下直接找权重文件（兜底，限定 1 层）
    for f in base.iterdir():
        if f.is_file() and f.suffix in (".pt", ".pth", ".bin", ".safetensors"):
            return _file_result(f, info)

    return None


def _search_modelscope(
    ms_root: Path, info: ResourceInfo
) -> ResourceStatusResult | None:
    """Search the canonical ModelScope cache layout only."""
    if not ms_root.exists():
        return None

    repo_name = info.ms_repo.split("/")[-1]
    ms_org = info.ms_repo.split("/")[0]

    # 新 SDK: hub/models/{org}/{repo}/
    for subdir in ["models", "hub/models"]:
        d = ms_root / subdir / ms_org / repo_name
        result = _search_in(d, info)
        if result:
            return result

    return None


def _check_model_snapshot(info: ResourceInfo | None) -> ResourceStatusResult:
    """检查 snapshot 类型模型是否已下载.

    按配置与缓存目录优先级顺序搜索:
    1. settings.json 的 model_cache_dir
    2. HF_HOME
    3. MODELSCOPE_CACHE (env + 默认)
    4. TORCH_HOME
    """
    from . import resource_manager as _rm

    if info is None:
        return _unknown_info_result()

    # 0. Project-bundled asset takes precedence (out-of-the-box, no download).
    bundled = bundled_model_asset(info)
    if bundled is not None:
        return _file_result(bundled, info)

    repo_name = info.ms_repo.split("/")[-1]
    ms_org = info.ms_repo.split("/")[0]

    # 1. MBForge 缓存目录
    cache_dir = _rm._get_model_cache_dir()
    local_dir = cache_dir / repo_name
    if _rm._has_weights(local_dir):
        return _snapshot_result(local_dir, info)
    if info.local_name:
        local_dir = cache_dir / info.local_name
        if _rm._has_weights(local_dir):
            return _snapshot_result(local_dir, info)

    # 2. HuggingFace 缓存
    hf_home = os.environ.get("HF_HOME", "")
    if hf_home:
        hf_dir = Path(hf_home) / repo_name
        if _rm._has_weights(hf_dir):
            return _snapshot_result(hf_dir, info)

    # 3. ModelScope 缓存（env > 默认）— canonical SDK layout only.
    ms_cache_candidates: list[Path] = []
    env_ms = os.environ.get("MODELSCOPE_CACHE", "")
    if env_ms:
        ms_cache_candidates.append(Path(env_ms))
    ms_cache_candidates.append(Path.home() / ".cache" / "modelscope")

    for ms_root in ms_cache_candidates:
        for subdir in ["", "models", "hub/models"]:
            ms_dir = ms_root / subdir / ms_org / repo_name
            if _rm._has_weights(ms_dir):
                return _snapshot_result(ms_dir, info)

    # 4. TORCH_HOME
    torch_home = os.environ.get("TORCH_HOME", "")
    if torch_home:
        torch_dir = Path(torch_home) / repo_name
        if _rm._has_weights(torch_dir):
            return _snapshot_result(torch_dir, info)

    return _result(info, ResourceStatus.NOT_FOUND)


def _check_model_file(info: ResourceInfo | None) -> ResourceStatusResult:
    """检查单文件/snapshot 类型模型是否已下载.

    搜索顺序: MBForge cache → HF_HOME → MODELSCOPE_CACHE → TORCH_HOME
    每个目录下同时搜索直接文件、子目录和 ModelScope canonical SDK 布局。
    """
    from . import resource_manager as _rm

    if info is None:
        return _unknown_info_result()

    # 1. MBForge 缓存
    result = _search_in(_rm._get_model_cache_dir(), info)
    if result:
        return result

    # 2. HF_HOME
    hf_home = os.environ.get("HF_HOME", "")
    if hf_home:
        result = _search_in(Path(hf_home), info)
        if result:
            return result

    # 3. MODELSCOPE_CACHE
    env_ms = os.environ.get("MODELSCOPE_CACHE", "")
    if env_ms:
        result = _search_modelscope(Path(env_ms), info)
        if result:
            return result
    result = _search_modelscope(Path.home() / ".cache" / "modelscope", info)
    if result:
        return result

    # 4. TORCH_HOME
    torch_home = os.environ.get("TORCH_HOME", "")
    if torch_home:
        result = _search_in(Path(torch_home), info)
        if result:
            return result

    return _result(info, ResourceStatus.NOT_FOUND)

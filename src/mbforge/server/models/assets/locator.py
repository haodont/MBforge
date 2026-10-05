"""Model cache discovery.

Scans the configured MBForge cache directory to locate already-downloaded
model weights. This module contains only read-only filesystem probes;
downloads live in ``models.assets.downloader`` and the public facade remains
``resource_manager.py``.
"""

# Tests:
#   tests/unit/core/test_resource_manager.py

from __future__ import annotations

from pathlib import Path

from mbforge.foundation.logger import get_logger
from mbforge.server.resource_types import (
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
    from mbforge.server import resource_manager as _rm

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
    repo_name = info.ms_repo.split("/")[-1] if info.ms_repo else ""
    for subdir_name in (repo_name, local_name, info.id):
        # 空名字会让 ``base / ""`` 退化成 ``base`` 本身，于是缓存根下的任意
        # 权重文件都会被当成这个模型的——候选必须是非空名字。
        if not subdir_name:
            continue
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


def _check_model_snapshot(info: ResourceInfo | None) -> ResourceStatusResult:
    """检查 snapshot 类型模型是否已下载.

    只认 MBForge 的模型缓存目录（``library/models``，可经
    ``model_cache_dir`` 覆盖）：该目录既是下载落点，也是唯一的读取来源。
    扫描 HF/ModelScope/Torch 的全局缓存会让"有没有下载好"取决于机器上别的
    工具留下的副本，所以那些位置不再参与判断。
    """
    from mbforge.server import resource_manager as _rm

    if info is None:
        return _unknown_info_result()

    cache_dir = _rm._get_model_cache_dir()
    repo_name = (info.ms_repo or info.hf_repo or info.id).split("/")[-1]

    # 下载落点目录优先（local_name），其次是仓库尾段名。
    candidates = [cache_dir / name for name in (info.local_name, repo_name) if name]
    candidates.append(cache_dir / info.id)
    for local_dir in candidates:
        if _rm._has_weights(local_dir):
            return _snapshot_result(local_dir, info)

    return _result(info, ResourceStatus.NOT_FOUND)


def _check_model_file(info: ResourceInfo | None) -> ResourceStatusResult:
    """检查单文件类型模型是否已下载（同样只认模型缓存目录）."""
    from mbforge.server import resource_manager as _rm

    if info is None:
        return _unknown_info_result()

    result = _search_in(_rm._get_model_cache_dir(), info)
    if result:
        return result
    return _result(info, ResourceStatus.NOT_FOUND)

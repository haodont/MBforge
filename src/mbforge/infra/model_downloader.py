"""Model download implementation.

Handles ModelScope SDK and direct-HTTP downloads into the MBForge model cache.
The public facade remains ``resource_manager.py``; callers should use
``ResourceManager.ensure()`` rather than these internals.
"""

from __future__ import annotations

import fnmatch
import shutil
from collections.abc import Callable
from pathlib import Path

from mbforge.utils.logger import get_logger

from .resource_types import ResourceInfo

logger = get_logger(__name__)

MS_BASE = "https://modelscope.cn/api/v1/models"


def _ensure_within(base: Path, candidate: Path) -> Path:
    """Return ``candidate`` resolved, refusing paths that escape ``base``.

    Download destinations derive from remote repo listings and catalog
    names, so a hostile entry must not be able to write outside the model
    cache.
    """
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"download destination escapes cache dir: {candidate}")
    return resolved


def _download_model_from_modelscope(
    info: ResourceInfo, callback: Callable[[dict], None] | None = None
) -> bool:
    """从 ModelScope 下载模型. 返回是否成功."""
    from . import resource_manager as _rm

    if info is None:
        return False

    cache_dir = _rm._get_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    def _emit(event: dict) -> None:
        if callback:
            callback(event)
        logger.info("Download event: %s", event)

    _emit({"status": "connecting", "source": "modelscope", "repo": info.ms_repo})

    if info.download_type == "snapshot":
        try:
            dest = _ensure_within(
                cache_dir, cache_dir / (info.local_name or info.ms_repo.split("/")[-1])
            )
        except ValueError as exc:
            _emit({"status": "failed", "error": str(exc)})
            return False
        dest.mkdir(parents=True, exist_ok=True)

        # 尝试 modelscope SDK
        try:
            from modelscope import snapshot_download as ms_snapshot

            _emit({"status": "downloading", "progress": 0})
            # 优先使用 `files` 字段(精确文件清单),否则用 `allow_patterns` (glob)
            ms_filter = info.files or info.allow_patterns
            try:
                ms_snapshot(
                    info.ms_repo,
                    local_dir=str(dest),
                    local_dir_use_symlinks=False,
                    allow_patterns=ms_filter or None,
                )
            except TypeError:
                # 新版 modelscope 不支持 local_dir_use_symlinks
                ms_snapshot(
                    info.ms_repo,
                    local_dir=str(dest),
                    allow_patterns=ms_filter or None,
                )
            if not _rm._verify_model_path(dest, info):
                shutil.rmtree(dest, ignore_errors=True)
                _emit({"status": "failed", "error": "下载完整性校验失败"})
                return False
            _emit({"status": "completed", "source": "modelscope"})
            return True
        except ImportError:
            # ModelScope SDK not installed — fall through to the direct-HTTP
            # download path (this is the normal CPU-only install case).
            logger.debug("ModelScope SDK not available, using direct HTTP download")
        except Exception as e:  # noqa: BLE001 — ModelScope SDK can raise anything (HTTP, FS, Auth). Log + fall through to direct-HTTP path.
            logger.warning("ModelScope SDK failed: %s", e)

        # 直接 HTTP 下载
        import requests as _requests

        _emit({"status": "downloading", "progress": 0})
        try:
            r = _requests.get(
                f"{MS_BASE}/{info.ms_repo}/repo/tree?Revision=master", timeout=30
            )
            tree = r.json().get("Data", []) if r.ok else []
            files = [f["Path"] for f in tree if f.get("Type") == "blob"]
        except Exception:  # noqa: BLE001 — listing request can fail (network, JSON); empty file list triggers the "failed" event below.
            files = []

        # 优先 `files` (精确清单) → `allow_patterns` (glob) → 不过滤
        patterns = info.files or info.allow_patterns
        if patterns:
            files = [f for f in files if any(fnmatch.fnmatch(f, p) for p in patterns)]

        if not files:
            _emit({"status": "failed", "error": "无法获取 ModelScope 文件列表"})
            return False

        for i, fpath in enumerate(files):
            try:
                fdest = _ensure_within(dest, dest / fpath)
            except ValueError as exc:
                _emit({"status": "failed", "error": str(exc)})
                return False
            fdest.parent.mkdir(parents=True, exist_ok=True)
            try:
                r = _requests.get(
                    f"{MS_BASE}/{info.ms_repo}/repo",
                    params={"Revision": "master", "FilePath": fpath},
                    timeout=300,
                    stream=True,
                )
                r.raise_for_status()
                fsize = int(r.headers.get("Content-Length", 0))
                got = 0
                # fdest is containment-validated by _ensure_within above.
                with fdest.open("wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                        got += len(chunk)
                        if fsize > 0:
                            _emit(
                                {
                                    "status": "downloading",
                                    "file": fpath,
                                    "file_progress": int(got * 100 / fsize),
                                    "file_index": i + 1,
                                    "total_files": len(files),
                                }
                            )
            except Exception as e:
                _emit({"status": "failed", "error": f"下载 {fpath} 失败: {e}"})
                return False

        if not _rm._verify_model_path(dest, info):
            shutil.rmtree(dest, ignore_errors=True)
            _emit({"status": "failed", "error": "下载完整性校验失败"})
            return False
        _emit({"status": "completed", "source": "modelscope"})
        return True

    # 单文件下载
    try:
        dest = _ensure_within(
            cache_dir, cache_dir / (info.local_name or f"{info.id}.pt")
        )
    except ValueError as exc:
        _emit({"status": "failed", "error": str(exc)})
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    import requests as _requests

    try:
        r = _requests.get(
            f"{MS_BASE}/{info.ms_repo}/repo",
            params={"Revision": "master", "FilePath": info.ms_file},
            timeout=300,
            stream=True,
        )
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        # dest is containment-validated by _ensure_within above.
        with dest.open("wb") as f:
            for chunk in r.iter_content(262144):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    _emit(
                        {
                            "status": "downloading",
                            "progress": int(downloaded * 100 / total),
                        }
                    )
        if not _rm._verify_model_path(dest, info):
            dest.unlink(missing_ok=True)
            _emit({"status": "failed", "error": "下载完整性校验失败"})
            return False
        _emit({"status": "completed", "source": "modelscope"})
        return True
    except Exception as e:
        _emit({"status": "failed", "error": str(e)})
        return False


def _download_model_from_hf(
    info: ResourceInfo, callback: Callable[[dict], None] | None = None
) -> bool:
    """从 HuggingFace 下载模型（ModelScope 失败时的兜底通道）.

    使用 ``huggingface_hub`` 按 ``info.files`` 精确下载，落点与 ModelScope
    通道一致（``<cache>/<repo 尾段>/``），避免全量 snapshot 拉取多余文件。
    """
    from . import resource_manager as _rm

    if info is None or not info.hf_repo:
        return False

    from mbforge.utils.paths import ensure_hf_mirror

    ensure_hf_mirror()  # HF_ENDPOINT → hf-mirror.com（未设置时）

    cache_dir = _rm._get_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    def _emit(event: dict) -> None:
        if callback:
            callback(event)
        logger.info("Download event: %s", event)

    _emit({"status": "connecting", "source": "huggingface", "repo": info.hf_repo})

    try:
        import huggingface_hub
    except ImportError as exc:
        _emit({"status": "failed", "error": f"huggingface_hub 未安装: {exc}"})
        return False

    if info.download_type == "snapshot":
        # 落点与 ModelScope 通道一致（用 local_name，而非各自 repo 尾段），
        # 保证 status 检查无论从哪条通道下载都能命中同一目录。
        dest = cache_dir / (info.local_name or info.hf_repo.split("/")[-1])
        dest.mkdir(parents=True, exist_ok=True)
        _emit({"status": "downloading", "progress": 0})
        try:
            huggingface_hub.snapshot_download(
                repo_id=info.hf_repo,
                local_dir=str(dest),
                allow_patterns=info.files or None,
            )
        except Exception as e:  # noqa: BLE001 — HF SDK can raise anything (HTTP/FS/auth)
            _emit({"status": "failed", "error": f"HF snapshot 下载失败: {e}"})
            return False
        if not _rm._verify_model_path(dest, info):
            shutil.rmtree(dest, ignore_errors=True)
            _emit({"status": "failed", "error": "下载完整性校验失败"})
            return False
        _emit({"status": "completed", "source": "huggingface"})
        return True

    # 单文件下载
    try:
        dest = _ensure_within(
            cache_dir, cache_dir / (info.local_name or f"{info.id}.pt")
        )
    except ValueError as exc:
        _emit({"status": "failed", "error": str(exc)})
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    filename = info.ms_file or (info.files[0] if info.files else "")
    try:
        huggingface_hub.hf_hub_download(
            repo_id=info.hf_repo,
            filename=filename,
            local_dir=str(dest.parent),
        )
    except Exception as e:  # noqa: BLE001
        _emit({"status": "failed", "error": f"HF 下载失败: {e}"})
        return False
    if not _rm._verify_model_path(dest, info):
        dest.unlink(missing_ok=True)
        _emit({"status": "failed", "error": "下载完整性校验失败"})
        return False
    _emit({"status": "completed", "source": "huggingface"})
    return True

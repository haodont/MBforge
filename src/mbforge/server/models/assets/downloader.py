"""Model download implementation.

Downloads model weights into the MBForge model cache (``library/models``).
The public facade remains ``resource_manager.py``; callers should use
``ResourceManager.ensure()`` rather than these internals.

Two channels are supported per the catalog:

- **ModelScope** (``info.ms_repo``) — the primary channel for domestic users.
  The SDK is tried first, but it can "succeed" while writing nothing (it does
  not raise when individual files fail), so every SDK attempt is verified and
  falls back to the direct-HTTP path on any shortfall.
- **HuggingFace** (``info.hf_repo``) — the fallback, and the only channel for
  repos that do not exist on ModelScope (Hiro-Layout, SLANet-1M).

Both channels write plain files (no symlinks) to
``<cache>/<info.local_name>/`` so a download is directly loadable by the
inference backends and a later re-check finds it without another download.

TLS note: some local HTTPS-intercepting proxies (e.g. SteamTools) present a
certificate the CA bundle does not trust, which fails *intermittently* as the
proxy is toggled. Direct HTTP requests therefore retry once without
certificate verification and log a warning; the failed-verification attempt is
always made first.
"""

# Tests:
#   tests/unit/core/test_model_downloader_dual_channel.py

from __future__ import annotations

import fnmatch
import shutil
from collections.abc import Callable
from pathlib import Path

import requests

from mbforge.foundation.logger import get_logger
from mbforge.server.resource_types import ResourceInfo

logger = get_logger(__name__)

MS_BASE = "https://modelscope.cn/api/v1/models"
HF_BASE = "https://huggingface.co"

#: Per-file streaming chunk. Large enough to keep the socket busy, small enough
#: that progress events stay responsive on a 250 MB ONNX download.
_CHUNK = 262144


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


def _is_ssl_error(exc: BaseException) -> bool:
    """Whether *exc* is a TLS trust failure rather than a transport problem."""
    text = f"{type(exc).__name__}: {exc}"
    return "CERTIFICATE_VERIFY_FAILED" in text or "SSLCertVerificationError" in text


def _get(
    url: str,
    *,
    params: dict | None = None,
    stream: bool = False,
    timeout: int = 300,
):
    """GET *url*, retrying once without TLS verification on a trust failure.

    Model weights are large binary artifacts fetched from a known host, so the
    signed-but-untrusted case (a local intercepting proxy) degrades to an
    unverified retry instead of failing the whole download. The exception is
    re-raised when the failure is not a certificate problem.
    """
    try:
        return requests.get(url, params=params, stream=stream, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — distinguish TLS trust from transport
        if not _is_ssl_error(exc):
            raise
        logger.warning(
            "TLS verification failed for %s (%s); retrying without certificate "
            "verification. Install the intercepting proxy's CA, or disable its "
            "HTTPS interception, to restore verified downloads.",
            url,
            type(exc).__name__,
        )
        return requests.get(
            url, params=params, stream=stream, timeout=timeout, verify=False
        )


def _filter_files(paths: list[str], info: ResourceInfo) -> list[str]:
    """Apply the catalog's exact ``files`` list, else its glob patterns."""
    if info.files:
        wanted = set(info.files)
        return [p for p in paths if p in wanted]
    patterns = info.allow_patterns or []
    if patterns:
        return [p for p in paths if any(fnmatch.fnmatch(p, pat) for pat in patterns)]
    return list(paths)


def _ms_list_files(info: ResourceInfo, timeout: int = 30) -> list[str]:
    """List a ModelScope repo's blob paths.

    Uses ``/repo/files``: the older ``/repo/tree`` endpoint now answers 404, and
    treating that as "no files" is what made the direct-HTTP path fail before it
    ever downloaded anything.
    """
    resp = _get(
        f"{MS_BASE}/{info.ms_repo}/repo/files",
        params={"Revision": "master"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        logger.warning(
            "ModelScope file listing for %s returned HTTP %s",
            info.ms_repo,
            resp.status_code,
        )
        return []
    data = resp.json().get("Data", {})
    entries = data.get("Files", []) if isinstance(data, dict) else []
    return [e["Path"] for e in entries if e.get("Type") == "blob" and e.get("Path")]


def _ms_download_file(
    info: ResourceInfo,
    path: str,
    dest: Path,
    emit: Callable[[dict], None],
    index: int,
    total: int,
) -> bool:
    """Stream one ModelScope file into *dest*. Returns success."""
    try:
        resp = _get(
            f"{MS_BASE}/{info.ms_repo}/repo",
            params={"Revision": "master", "FilePath": path},
            stream=True,
            timeout=600,
        )
        resp.raise_for_status()
        target = _ensure_within(dest, dest / path)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = int(resp.headers.get("Content-Length", 0) or 0)
        got = 0
        with target.open("wb") as fh:
            for chunk in resp.iter_content(_CHUNK):
                fh.write(chunk)
                got += len(chunk)
                if size > 0:
                    emit(
                        {
                            "status": "downloading",
                            "file": path,
                            "file_progress": int(got * 100 / size),
                            "file_index": index,
                            "total_files": total,
                        }
                    )
        return True
    except ValueError as exc:
        emit({"status": "failed", "error": str(exc)})
        return False
    except Exception as exc:  # noqa: BLE001 — one bad file must not abort the rest
        logger.warning("ModelScope download of %s failed: %s", path, exc)
        emit({"status": "failed", "error": f"下载 {path} 失败: {exc}"})
        return False


def _modelscope_direct_http(
    info: ResourceInfo, dest: Path, emit: Callable[[dict], None]
) -> bool:
    """Download every catalog file over plain HTTPS (no ModelScope SDK).

    This is the reliable channel: it needs no SDK lock directory, reports each
    file's progress, and works for repos the SDK fails on.
    """
    if not info.ms_repo:
        return False

    listed = _ms_list_files(info)
    files = _filter_files(listed, info)
    if not files:
        # The catalog manifest is authoritative when the listing is unavailable;
        # per-file GETs then fail individually rather than aborting up front.
        files = list(info.files)
    if not files:
        emit({"status": "failed", "error": "无法获取 ModelScope 文件列表"})
        return False

    total = len(files)
    for i, path in enumerate(files, start=1):
        if not _ms_download_file(info, path, dest, emit, i, total):
            return False
    return True


def _download_model_from_modelscope(
    info: ResourceInfo, callback: Callable[[dict], None] | None = None
) -> bool:
    """Download a model from ModelScope. Returns whether it succeeded.

    The SDK is attempted first for speed and resume support; because it does not
    raise when every file fails, the result is verified and the direct-HTTP path
    takes over. Without that hand-off a silent SDK failure left the model
    permanently undownloadable even though the plain-HTTP channel worked.
    """
    from mbforge.server import resource_manager as _rm

    if info is None:
        return False

    cache_dir = _rm._get_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    def _emit(event: dict) -> None:
        if callback:
            callback(event)
        logger.info("Download event: %s", event)

    _emit({"status": "connecting", "source": "modelscope", "repo": info.ms_repo})

    if not info.ms_repo:
        return False

    if info.download_type == "snapshot":
        try:
            dest = _ensure_within(
                cache_dir, cache_dir / (info.local_name or info.ms_repo.split("/")[-1])
            )
        except ValueError as exc:
            _emit({"status": "failed", "error": str(exc)})
            return False
        dest.mkdir(parents=True, exist_ok=True)

        if _ms_try_sdk(info, dest, _emit) and _rm._verify_model_path(dest, info):
            _emit({"status": "completed", "source": "modelscope"})
            return True

        # SDK ran but left the snapshot incomplete (or raised): clear the
        # partial directory and use the direct-HTTP channel.
        if any(dest.iterdir()):
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        logger.info(
            "ModelScope SDK did not produce a complete %s snapshot; "
            "falling back to direct HTTP download",
            info.id,
        )
        _emit({"status": "downloading", "progress": 0, "source": "modelscope-http"})
        if not _modelscope_direct_http(info, dest, _emit):
            shutil.rmtree(dest, ignore_errors=True)
            return False
        if not _rm._verify_model_path(dest, info):
            shutil.rmtree(dest, ignore_errors=True)
            _emit({"status": "failed", "error": "下载完整性校验失败"})
            return False
        _emit({"status": "completed", "source": "modelscope"})
        return True

    # Single-file resource.
    try:
        dest = _ensure_within(
            cache_dir, cache_dir / (info.local_name or f"{info.id}.pt")
        )
    except ValueError as exc:
        _emit({"status": "failed", "error": str(exc)})
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)

    ok = _ms_download_single(info, dest, _emit)
    if not ok:
        dest.unlink(missing_ok=True)
        return False
    if not _rm._verify_model_path(dest, info):
        dest.unlink(missing_ok=True)
        _emit({"status": "failed", "error": "下载完整性校验失败"})
        return False
    _emit({"status": "completed", "source": "modelscope"})
    return True


def _ms_try_sdk(info: ResourceInfo, dest: Path, emit: Callable[[dict], None]) -> bool:
    """Attempt the ModelScope SDK download. Returns whether it ran to completion.

    A ``True`` result only means the call returned; the caller still verifies the
    snapshot.
    """
    try:
        from modelscope import snapshot_download as ms_snapshot
    except ImportError:
        logger.debug("ModelScope SDK not available, using direct HTTP download")
        return False

    emit({"status": "downloading", "progress": 0})
    ms_filter = info.files or info.allow_patterns
    try:
        try:
            ms_snapshot(
                info.ms_repo,
                local_dir=str(dest),
                local_dir_use_symlinks=False,
                allow_patterns=ms_filter or None,
            )
        except TypeError:
            # Newer modelscope builds dropped ``local_dir_use_symlinks``.
            ms_snapshot(
                info.ms_repo, local_dir=str(dest), allow_patterns=ms_filter or None
            )
        return True
    except Exception as exc:  # noqa: BLE001 — SDK raises HTTP/FS/auth errors alike
        logger.warning("ModelScope SDK download failed for %s: %s", info.id, exc)
        return False


def _ms_download_single(
    info: ResourceInfo, dest: Path, emit: Callable[[dict], None]
) -> bool:
    """Download a single-file ModelScope resource with progress reporting."""
    try:
        resp = _get(
            f"{MS_BASE}/{info.ms_repo}/repo",
            params={"Revision": "master", "FilePath": info.ms_file},
            stream=True,
            timeout=600,
        )
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(_CHUNK):
                fh.write(chunk)
                done += len(chunk)
                if total > 0:
                    emit(
                        {
                            "status": "downloading",
                            "progress": int(done * 100 / total),
                        }
                    )
        return True
    except Exception as exc:  # noqa: BLE001
        emit({"status": "failed", "error": str(exc)})
        return False


def _hf_api_base() -> str:
    """Return the configured HuggingFace endpoint (mirror-aware), no slash."""
    from mbforge.foundation.paths import ensure_hf_mirror

    ensure_hf_mirror()
    import os

    return (os.environ.get("HF_ENDPOINT") or HF_BASE).rstrip("/")


def _hf_resolve_url(info: ResourceInfo, path: str) -> str:
    """Build the HuggingFace download URL for one repo file."""
    return f"{_hf_api_base()}/{info.hf_repo}/resolve/main/{path}"


def _hf_download_file(
    info: ResourceInfo,
    path: str,
    dest: Path,
    emit: Callable[[dict], None],
    index: int,
    total: int,
) -> bool:
    """Stream one HuggingFace file into *dest*, following CDN redirects."""
    try:
        resp = _get(_hf_resolve_url(info, path), stream=True, timeout=900)
        resp.raise_for_status()
        target = _ensure_within(dest, dest / path)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = int(resp.headers.get("Content-Length", 0) or 0)
        got = 0
        with target.open("wb") as fh:
            for chunk in resp.iter_content(_CHUNK):
                fh.write(chunk)
                got += len(chunk)
                if size > 0:
                    emit(
                        {
                            "status": "downloading",
                            "file": path,
                            "file_progress": int(got * 100 / size),
                            "file_index": index,
                            "total_files": total,
                        }
                    )
        return True
    except ValueError as exc:
        emit({"status": "failed", "error": str(exc)})
        return False
    except Exception as exc:  # noqa: BLE001 — one bad file must not abort the rest
        logger.warning("HuggingFace download of %s failed: %s", path, exc)
        emit({"status": "failed", "error": f"下载 {path} 失败: {exc}"})
        return False


def _hf_list_files(info: ResourceInfo, timeout: int = 30) -> list[str]:
    """List a HuggingFace repo's file paths via the tree API."""
    try:
        resp = _get(
            f"{_hf_api_base()}/api/models/{info.hf_repo}/tree/main",
            params={"recursive": "true"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        entries = resp.json()
        return [
            e["path"]
            for e in entries
            if isinstance(e, dict) and e.get("type") == "file" and e.get("path")
        ]
    except Exception as exc:  # noqa: BLE001 — listing is best-effort
        logger.debug("HF tree listing unavailable for %s: %s", info.hf_repo, exc)
        return []


def _download_model_from_hf(
    info: ResourceInfo, callback: Callable[[dict], None] | None = None
) -> bool:
    """Download a model from HuggingFace over plain HTTPS.

    Uses the catalog's exact file list so no extra listing round-trip is needed;
    a repo whose manifest is empty falls back to the tree API. Files land in the
    same ``<cache>/<local_name>/`` layout as the ModelScope channel, so the
    status check finds a download from either channel.
    """
    from mbforge.server import resource_manager as _rm

    if info is None or not info.hf_repo:
        return False

    cache_dir = _rm._get_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    def _emit(event: dict) -> None:
        if callback:
            callback(event)
        logger.info("Download event: %s", event)

    _emit({"status": "connecting", "source": "huggingface", "repo": info.hf_repo})

    if info.download_type != "snapshot":
        dest = cache_dir / (info.local_name or f"{info.id}.pt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        filename = info.ms_file or (info.files[0] if info.files else "")
        if not filename:
            _emit({"status": "failed", "error": "未指定 HF 下载文件"})
            return False
        if not _hf_download_file(info, filename, dest.parent, _emit, 1, 1):
            return False
        if not _rm._verify_model_path(dest, info):
            dest.unlink(missing_ok=True)
            _emit({"status": "failed", "error": "下载完整性校验失败"})
            return False
        _emit({"status": "completed", "source": "huggingface"})
        return True

    dest = cache_dir / (info.local_name or info.hf_repo.split("/")[-1])
    dest.mkdir(parents=True, exist_ok=True)

    files = list(info.files) or _filter_files(_hf_list_files(info), info)
    if not files:
        _emit({"status": "failed", "error": "无法获取 HuggingFace 文件列表"})
        return False

    total = len(files)
    for i, path in enumerate(files, start=1):
        if not _hf_download_file(info, path, dest, _emit, i, total):
            shutil.rmtree(dest, ignore_errors=True)
            return False

    if not _rm._verify_model_path(dest, info):
        shutil.rmtree(dest, ignore_errors=True)
        _emit({"status": "failed", "error": "下载完整性校验失败"})
        return False
    _emit({"status": "completed", "source": "huggingface"})
    return True

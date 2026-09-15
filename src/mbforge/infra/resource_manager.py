"""Unified resource manager for environment setup, dependency downloads, and runtime checks.

Central registry and installer for external resources (models, Python packages,
and binary tools). Models default to ModelScope, Python packages default to the
Tsinghua mirror. All runtime availability checks flow through this module so
the CLI and server can fail fast before starting the pipeline.

The heavy cache-discovery and download implementations have moved to
``model_locator`` and ``model_downloader``; this module re-exports the names
used by existing callers so imports remain unchanged.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from mbforge.utils.files import dir_size_bytes as _helpers_dir_size_bytes
from mbforge.utils.files import sha256_file as _helpers_sha256_file
from mbforge.utils.logger import get_logger

from .resource_types import (
    EnvironmentReport,
    ResourceInfo,
    ResourceStatus,
    ResourceStatusResult,
    ResourceType,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 资源目录（唯一真相源）
# ---------------------------------------------------------------------------

# 清华 PyPI 镜像
TSINGHUA_PIP = "https://pypi.tuna.tsinghua.edu.cn/simple"

RESOURCE_CATALOG: dict[str, ResourceInfo] = {
    # ──── 模型（ModelScope 优先，HuggingFace 兜底双通道下载）────
    "moldet": ResourceInfo(
        id="moldet",
        name="MolDetv2-YOLO26",
        type=ResourceType.MODEL,
        description="MolDetv2 (YOLO26) 分子检测器，仅识别分子结构（无 coref 标识符）",
        size_mb=12,
        license="cc-by-nc-sa-4.0",
        # 注意：ModelScope 的 UniParser/MolDetv2 仓库只有 yolo11n 权重；yolo26n
        # 变体在 MS 的 UniParser/MolDetv2-YOLO26（以及 HF 同名仓库）。两条通道
        # 都指向 YOLO26 仓库，国内走 MS 即达。后续自训/微调权重上传后覆盖本目录。
        ms_repo="UniParser/MolDetv2-YOLO26",
        hf_repo="UniParser/MolDetv2-YOLO26",
        download_type="snapshot",
        local_name="MolDetv2",
        files=[
            "moldet_v2_yolo26n_960_doc.pt",
            "moldet_v2_yolo26n_640_general.pt",
        ],
        allow_patterns=["*.pt"],  # 排除 .onnx
    ),
    "molparser": ResourceInfo(
        id="molparser",
        name="MolParser-Mobile",
        type=ResourceType.MODEL,
        description="MolParser-Mobile 分子结构图 → E-SMILES",
        size_mb=20,
        license="cc-by-nc-sa-4.0",
        license_url="https://github.com/dptech-corp/MolParser/blob/main/LICENSE",
        ms_repo="UniParser/MolParser-Mobile",
        hf_repo="UniParser/MolParser-Mobile",
        download_type="snapshot",
        local_name="MolParser-Mobile",
        source_url="https://github.com/dptech-corp/MolParser",
        files=[
            "config.json",
            "generation_config.json",
            "preprocessor_config.json",
            "processor_config.json",
            "tokenizer_config.json",
            "image_processing_molparser_mobile.py",
            "modeling_molparser_mobile.py",
            "processing_molparser_mobile.py",
            "tokenization_molparser_mobile.py",
            "model.safetensors",
            "vocab.txt",
        ],
    ),
    # ──── Python 包（清华源）────
    "rdkit": ResourceInfo(
        id="rdkit",
        name="RDKit",
        type=ResourceType.PYTHON_PACKAGE,
        description="分子信息学: SMILES 解析、分子属性计算",
        license="BSD-3",
        pip_name="rdkit",
        import_name="rdkit",
        mirror=TSINGHUA_PIP,
    ),
    "torch": ResourceInfo(
        id="torch",
        name="PyTorch",
        type=ResourceType.PYTHON_PACKAGE,
        description="深度学习框架 (CUDA 12.8)",
        license="BSD-3",
        pip_name="torch",
        import_name="torch",
        mirror=TSINGHUA_PIP,
    ),
    "transformers": ResourceInfo(
        id="transformers",
        name="Transformers",
        type=ResourceType.PYTHON_PACKAGE,
        description="Hugging Face 模型加载框架",
        pip_name="transformers",
        import_name="transformers",
        mirror=TSINGHUA_PIP,
    ),
    "ultralytics": ResourceInfo(
        id="ultralytics",
        name="Ultralytics",
        type=ResourceType.PYTHON_PACKAGE,
        description="YOLO 目标检测框架 (MolDet 依赖)",
        license="AGPL-3.0",
        pip_name="ultralytics",
        import_name="ultralytics",
        mirror=TSINGHUA_PIP,
    ),
}

# Optional libraries are imported only at their call sites and have a
# deterministic fallback. They should not make the startup environment report
# look unhealthy when absent.
ENVIRONMENT_CHECK_EXCLUDED: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# 检查函数
# ---------------------------------------------------------------------------


def _get_model_cache_dir() -> Path:
    """获取模型缓存目录."""
    from mbforge.utils.paths import get_model_cache_dir

    return Path(get_model_cache_dir())


def _has_weights(path: Path) -> bool:
    """检查目录中是否包含模型权重文件."""
    if not path.exists():
        return False
    return (
        any(path.rglob("*.bin"))
        or any(path.rglob("*.safetensors"))
        or any(path.rglob("*.pt"))
        or any(path.rglob("*.pth"))
    )


def _dir_size(path: Path) -> float:
    """计算目录中所有文件的总大小（MB）."""
    return round(_helpers_dir_size_bytes(path) / 1024 / 1024, 1)


def _compute_sha256(path: Path) -> str:
    """计算文件的 SHA-256 摘要（委托至 files.sha256_file 保持单一实现）."""
    return _helpers_sha256_file(path)


def _dir_size_bytes(path: Path) -> int:
    """计算目录中所有文件的总大小（字节）."""
    return _helpers_dir_size_bytes(path)


def _matches_expected_size(path: Path, info: ResourceInfo) -> bool:
    """Check the configured primary artifact size without counting sidecars."""
    if info.expected_size <= 0:
        return True
    if path.is_dir() and info.files and len(info.files) == 1:
        target = path / info.files[0]
        return target.is_file() and target.stat().st_size == info.expected_size
    if path.is_file():
        return path.stat().st_size == info.expected_size
    return _dir_size_bytes(path) == info.expected_size


def _verify_model_path(path: Path, info: ResourceInfo) -> bool:
    """校验已下载模型文件的哈希与尺寸.

    - 文件类型：直接校验 ``path``。
    - snapshot 类型：若 ``info.files`` 仅含一个文件且提供 ``sha256``，
      则校验该子文件；否则仅校验目录总大小（如提供）。
    """
    if info is None:
        return False
    if not path.exists():
        return False

    if path.is_file():
        target = path
    elif path.is_dir() and info.sha256 and info.files and len(info.files) == 1:
        target = path / info.files[0]
        if not target.is_file():
            logger.error("Integrity check file not found: %s", target)
            return False
    else:
        target = None

    if target is not None:
        if info.expected_size > 0 and target.stat().st_size != info.expected_size:
            logger.error(
                "%s size mismatch: expected=%d, got=%d",
                info.id,
                info.expected_size,
                target.stat().st_size,
            )
            return False
        if info.sha256:
            actual = _compute_sha256(target)
            if actual != info.sha256:
                logger.error(
                    "%s SHA-256 mismatch: expected=%s, got=%s",
                    info.id,
                    info.sha256,
                    actual,
                )
                return False
        return True

    if path.is_dir() and info.files:
        missing = [f for f in info.files if not (path / f).is_file()]
        if missing:
            logger.error(
                "%s missing expected files: %s",
                info.id,
                ", ".join(missing),
            )
            return False

    if info.expected_size > 0:
        actual = _dir_size_bytes(path)
        if actual != info.expected_size:
            logger.error(
                "%s directory size mismatch: expected=%d, got=%d",
                info.id,
                info.expected_size,
                actual,
            )
            return False
    return True


# The locator/downloader implementations are imported lazily (inside the
# accessors below and the dispatch functions) so that ``resource_manager``
# never forms an import cycle with them: ``model_locator``/``model_downloader``
# reference this module only at call time via ``from . import resource_manager``.
# The names stay module attributes so existing callers and tests that patch
# ``mbforge.infra.resource_manager._check_model_*`` / ``_download_model_from_*``
# keep working.


def _load_locator() -> tuple[object, object]:
    from .model_locator import _check_model_file, _check_model_snapshot

    return _check_model_file, _check_model_snapshot


def _check_model_file(info: ResourceInfo | None) -> ResourceStatusResult:
    return _load_locator()[0](info)


def _check_model_snapshot(info: ResourceInfo | None) -> ResourceStatusResult:
    return _load_locator()[1](info)


def _download_model_from_modelscope(
    info: ResourceInfo, callback: Callable[[dict], None] | None = None
) -> bool:
    from .model_downloader import _download_model_from_modelscope as _impl

    return _impl(info, callback)


def _download_model_from_hf(
    info: ResourceInfo, callback: Callable[[dict], None] | None = None
) -> bool:
    from .model_downloader import _download_model_from_hf as _impl

    return _impl(info, callback)


def _check_python_package(info: ResourceInfo) -> ResourceStatusResult:
    """检查 Python 包是否已安装."""
    import_name = info.import_name or info.pip_name
    try:
        mod = importlib.import_module(import_name)
        ver = getattr(mod, "__version__", "")
        return ResourceStatusResult(
            id=info.id,
            name=info.name,
            type=info.type,
            status=ResourceStatus.READY,
            version=ver,
        )
    except ImportError:
        return ResourceStatusResult(
            id=info.id,
            name=info.name,
            type=info.type,
            status=ResourceStatus.NOT_FOUND,
        )


# ---------------------------------------------------------------------------
# 下载/安装函数
# ---------------------------------------------------------------------------


def _install_python_package(
    info: ResourceInfo, callback: Callable[[dict], None] | None = None
) -> bool:
    """通过 pip 安装 Python 包. 返回是否成功."""
    if info is None:
        return False

    def _emit(event: dict):
        if callback:
            callback(event)

    pip_name = info.pip_name
    mirror = info.mirror or TSINGHUA_PIP
    cmd = [sys.executable, "-m", "pip", "install", pip_name, "-i", mirror]

    _emit({"status": "downloading", "progress": 0})
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            _emit({"status": "completed"})
            return True
        else:
            _emit(
                {
                    "status": "failed",
                    "error": result.stderr[-500:] if result.stderr else "Unknown error",
                }
            )
            return False
    except subprocess.TimeoutExpired:
        _emit({"status": "failed", "error": "安装超时"})
        return False
    except Exception as e:
        _emit({"status": "failed", "error": str(e)})
        return False


# ---------------------------------------------------------------------------
# 检查分发
# ---------------------------------------------------------------------------


def _check_resource(resource_id: str) -> ResourceStatusResult:
    """检查单个资源的状态.

    通过本地文件系统扫描判断资源是否就绪。单个资源异常不会影响其他资源。
    """
    try:
        info = RESOURCE_CATALOG.get(resource_id)
        if info is None:
            return ResourceStatusResult(
                id=resource_id,
                name=resource_id,
                type=ResourceType.MODEL,
                status=ResourceStatus.ERROR,
                error=f"未知资源: {resource_id}",
            )

        # 本地扫描
        if info.type == ResourceType.MODEL:
            if info.download_type == "file":
                return _check_model_file(info)
            else:
                return _check_model_snapshot(info)
        elif info.type == ResourceType.PYTHON_PACKAGE:
            return _check_python_package(info)
        elif info.type == ResourceType.BINARY:
            return ResourceStatusResult(
                id=resource_id,
                name=info.name,
                type=info.type,
                status=ResourceStatus.NOT_FOUND,
            )
        else:
            return ResourceStatusResult(
                id=resource_id,
                name=info.name,
                type=info.type,
                status=ResourceStatus.NOT_FOUND,
            )
    except Exception as e:
        return ResourceStatusResult(
            id=resource_id,
            name=resource_id,
            type=ResourceType.MODEL,
            status=ResourceStatus.ERROR,
            error=str(e),
        )


def _record_model_outcome(resource_id: str, error: str | None) -> None:
    """Persist the last ensure() outcome for the readiness diagnostics.

    Failure reasons are truncated (defense-in-depth sanitization); success
    clears any previously recorded reason. Status writes go through
    :func:`mbforge.infra.models.ensure` so download/load outcomes share one
    state channel with prewarm and the model lifecycle endpoints.
    """
    try:
        from .models import ensure as ensure_model_status

        ensure_model_status(
            resource_id,
            {"status": "error", "error": error} if error else {"status": "ready"},
        )
    except Exception:  # noqa: BLE001 — diagnostics must never break ensure()
        logger.debug("Failed to record model outcome", exc_info=True)


def _read_resolved_paths() -> dict[str, str]:
    """Load Rust-side resolved model paths when available.

    Returns an empty mapping if the resolved-paths file is missing or invalid.
    """
    try:
        from mbforge.utils.files import safe_json_loads
        from mbforge.utils.paths import GLOBAL_APP_DIR

        text = (GLOBAL_APP_DIR / "resolved_paths.json").read_text(encoding="utf-8")
        data = safe_json_loads(text, {})
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:  # noqa: BLE001 — best-effort fallback path
        # resolved_paths.json is produced by the Rust sidecar; absent or stale
        # files are normal (paths resolve via the catalog instead).
        logger.debug("resolved_paths.json unavailable, using catalog defaults: %s", exc)
    return {}


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


class ResourceManager:
    """统一资源管理器."""

    catalog = RESOURCE_CATALOG

    @classmethod
    def check(cls, resource_id: str) -> ResourceStatusResult:
        """检查单个资源状态."""
        return _check_resource(resource_id)

    @classmethod
    def check_all(cls) -> EnvironmentReport:
        """全量环境检查."""
        report = EnvironmentReport()

        # Python 版本
        report.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        # GPU
        try:
            import torch

            if torch.cuda.is_available():
                report.gpu_available = True
                report.gpu_name = torch.cuda.get_device_name(0)
                report.cuda_version = torch.version.cuda
        except ImportError:
            # torch is optional (CPU-only installs) — leave the GPU section off.
            logger.debug("torch not importable, skipping GPU detection")

        # 逐个检查资源
        for resource_id in RESOURCE_CATALOG:
            if resource_id in ENVIRONMENT_CHECK_EXCLUDED:
                continue
            report.resources.append(_check_resource(resource_id))

        return report

    @classmethod
    def ensure(
        cls, resource_id: str, callback: Callable[[dict], None] | None = None
    ) -> ResourceStatusResult:
        """确保资源可用（缺失则下载/安装）."""
        status = cls.check(resource_id)
        if status.status == ResourceStatus.READY:
            return status

        info = RESOURCE_CATALOG.get(resource_id)
        if info is None:
            return status

        # Capture the last failure reason emitted through the progress
        # callback so it can be persisted for the readiness diagnostics.
        last_failure: list[str] = []

        def _tracking_callback(event: dict) -> None:
            if event.get("status") == "failed" and event.get("error"):
                last_failure.append(str(event["error"]))
            if callback is not None:
                callback(event)

        success = False
        if info.type == ResourceType.MODEL:
            # 双通道下载：国内优先 ModelScope，失败（网络/文件缺失/校验失败）
            # 时回退 HuggingFace（HF_ENDPOINT 由 ensure_hf_mirror 指向镜像）。
            success = _download_model_from_modelscope(info, _tracking_callback)
            if not success and info.hf_repo:
                logger.info(
                    "ModelScope download failed for %s; falling back to "
                    "HuggingFace repo %s",
                    info.id,
                    info.hf_repo,
                )
                success = _download_model_from_hf(info, _tracking_callback)
        elif info.type == ResourceType.PYTHON_PACKAGE:
            success = _install_python_package(info, _tracking_callback)
        elif info.type == ResourceType.BINARY:
            if callback:
                callback(
                    {
                        "status": "failed",
                        "error": f"二进制资源 {info.name} 需要手动安装，请参考项目文档",
                    }
                )
            return status

        if info.type == ResourceType.MODEL:
            if success:
                result = cls.check(resource_id)
                if result.status == ResourceStatus.READY:
                    _record_model_outcome(resource_id, None)
                else:
                    _record_model_outcome(
                        resource_id, result.error or "下载后校验未通过"
                    )
                return result
            _record_model_outcome(
                resource_id,
                (last_failure[-1] if last_failure else None)
                or status.error
                or "下载失败",
            )
            return status

        if success:
            return cls.check(resource_id)
        return status

    @classmethod
    def get_model_path(cls, resource_id: str) -> Path | None:
        """获取已下载模型的本地路径（供模型加载使用）."""
        status = cls.check(resource_id)
        if status.status == ResourceStatus.READY and status.local_path:
            return Path(status.local_path)
        return None

    @classmethod
    def get_molparser_path(cls) -> Path | None:
        """获取 MolParser-Mobile 模型目录（含 model.safetensors，供识别后端加载）."""
        path = cls.get_model_path("molparser")
        if path and path.exists():
            return path
        return None

    @classmethod
    def resolve_model_for_backend(
        cls, resource_id: str, subpath: str | None = None
    ) -> Path | None:
        """后端统一入口：解析模型路径，找不到返回 None.

        所有 Python 后端（moldet、molparser）应使用此方法
        而非自行实现路径搜索逻辑。
        返回值：
        - snapshot 类型：返回包含权重文件的目录
        - file 类型：返回具体权重文件路径
        - subpath 指定时：返回 `<resolved_dir>/<subpath>`（用于多文件资源的子文件定位）
        """
        # Python 侧扫描
        info = RESOURCE_CATALOG.get(resource_id)
        status = cls.check(resource_id)
        if status.status == ResourceStatus.READY and status.local_path:
            p = Path(status.local_path)
            if info and info.download_type == "snapshot":
                # snapshot 类型：返回目录（让调用方自己找具体文件）
                base = p.parent if p.is_file() else p
                if subpath:
                    full = base / subpath
                    if full.exists():
                        return full
                    # Project-bundled single-file asset (e.g. assets/models/
                    # moldetv2_structure_ft.pt): subpath does not apply, so
                    # return the file itself when the resolved path is a file.
                    if p.is_file() and p.exists():
                        return p
                    return None
                return base
            return p
        return None

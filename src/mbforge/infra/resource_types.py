"""Shared resource data types.

The resource catalog entries (:class:`ResourceInfo`), status enums and report
shapes used across :mod:`mbforge.infra.resource_manager`, the cache-discovery
module (:mod:`mbforge.infra.model_locator`) and the downloader
(:mod:`mbforge.infra.model_downloader`). Keeping them in a dependency-free
module lets the three implementation modules import them without forming an
import cycle.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ResourceType(enum.StrEnum):
    MODEL = "model"
    PYTHON_PACKAGE = "python_package"
    BINARY = "binary"
    NODE_PACKAGE = "node_package"


class ResourceStatus(enum.StrEnum):
    READY = "ready"  # 已就绪
    NOT_FOUND = "not_found"  # 未下载/未安装
    PARTIAL = "partial"  # 部分就绪（如目录存在但缺文件）
    ERROR = "error"  # 检查出错
    DOWNLOADING = "downloading"  # 下载中


@dataclass
class ResourceInfo:
    """资源目录条目."""

    id: str
    name: str
    type: ResourceType
    description: str
    size_mb: float = 0
    license: str = ""
    license_url: str = ""
    # 模型专用
    ms_repo: str = ""  # ModelScope 仓库 ID
    hf_repo: str = ""  # HuggingFace 仓库 ID（备用/元数据）
    download_type: str = "snapshot"  # snapshot | file
    ms_file: str = ""  # 单文件下载时的远程文件名
    local_name: str = ""  # 本地文件名
    source_url: str = ""  # 项目主页
    allow_patterns: list[str] = field(
        default_factory=list
    )  # snapshot 下载时仅匹配的文件模式
    files: list[str] = field(
        default_factory=list
    )  # 资源包含的具体文件列表（与 Rust 端保持一致）
    # 完整性校验（模型专用）
    sha256: str = ""  # 主文件的期望 SHA-256 摘要
    expected_size: int = 0  # 主文件/目录的期望字节数
    # Python 包专用
    pip_name: str = ""  # pip 包名
    import_name: str = ""  # import 名（与 pip 名不同时）
    mirror: str = ""  # 镜像源 URL


@dataclass
class ResourceStatusResult:
    """单个资源的检查结果."""

    id: str
    name: str
    type: ResourceType
    status: ResourceStatus
    local_path: str = ""
    size_mb: float = 0
    version: str = ""
    error: str = ""


@dataclass
class EnvironmentReport:
    """全量环境检查报告."""

    python_version: str = ""
    gpu_available: bool = False
    gpu_name: str = ""
    cuda_version: str = ""
    resources: list[ResourceStatusResult] = field(default_factory=list)

    @property
    def summary(self) -> str:
        ready = sum(1 for r in self.resources if r.status == ResourceStatus.READY)
        total = len(self.resources)
        missing = [r.name for r in self.resources if r.status != ResourceStatus.READY]
        if missing:
            return f"{ready}/{total} resources ready (missing: {', '.join(missing)})"
        return f"{ready}/{total} resources ready"

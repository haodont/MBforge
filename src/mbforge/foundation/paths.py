"""Application metadata and path helpers.

Defines static constants shared across the backend: application name,
version, global directories (config/logs/model cache), and utility
functions for resolving library roots and ensuring Hugging Face mirror
configuration. Runtime configuration lives in ``settings.json``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 应用元信息 — 编译期固定,不改
APP_NAME = "MBForge"
APP_VERSION = "0.3.0"

# 源码根目录 — 本项目以源码文件夹分发,运行时数据(config/logs/模型/库数据)统一
# 落在源码文件夹内的 library/ 下:整个文件夹拷走即可迁移,也避免 Windows 上
# %APPDATA% 与 %LOCALAPPDATA% 分裂导致的混乱.安装成 wheel 时本文件位于
# site-packages 内,没有可写的源码目录,回退到 ~/MBForge,避免污染 site-packages.
_SOURCE_ROOT = Path(__file__).resolve().parents[3]
GLOBAL_APP_DIR = (
    _SOURCE_ROOT / "library"
    if (_SOURCE_ROOT / "pyproject.toml").is_file()
    else Path.home() / "MBForge"
)
GLOBAL_SETTINGS_PATH = GLOBAL_APP_DIR / "settings.json"

# 后端 sidecar 端口 — __main__ 启动参数 fallback
DEFAULT_SIDECAR_PORT = 18792

# HF 镜像 endpoint — ensure_hf_mirror() 在 HF_ENDPOINT 未设置时使用
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"


def get_model_cache_dir() -> str:
    """模型缓存目录(优先 settings.json,其次默认路径).

    Returns 展开 ~ 后的绝对路径字符串.
    """
    try:
        from mbforge.foundation.config import load_global_config

        cfg = load_global_config()
        if cfg.model_cache_dir:
            raw = cfg.model_cache_dir
            if raw.startswith("~/") or raw.startswith("~\\"):
                return str(Path.home() / raw[2:])
            if raw == "~":
                return str(Path.home())
            return str(Path(raw).expanduser().resolve())
    except Exception as exc:
        logger.debug("Failed to read model_cache_dir from settings: %s", exc)
    return str(GLOBAL_APP_DIR / "models")


def is_within_global_app_dir(path: str | Path) -> bool:
    """Return True if ``path`` is the global app dir or inside it.

    Library data must never live inside the application global directory
    when the user has explicitly set a separate ``library_root``; however,
    when ``library_root`` defaults to ``GLOBAL_APP_DIR`` this check returns
    True by design.
    """
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return False
    try:
        resolved.relative_to(GLOBAL_APP_DIR.resolve())
        return True
    except ValueError:
        return False


def ensure_hf_mirror() -> None:
    """设置 HuggingFace 镜像环境变量(若未设置)."""
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = DEFAULT_HF_ENDPOINT

"""Runtime helpers: ids, sync-in-async, path validation.

Device probing and model unload orchestration live upstream (see
TODO/services-layer-plan.md A4) — utils stays dependency-free.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mbforge.utils.logger import get_logger

logger = get_logger(__name__)


def generate_uuid() -> str:
    """生成唯一标识符."""
    return str(uuid.uuid4())


def run_sync(sync_func: Callable[..., Any], *args: Any) -> Any:
    """在当前事件循环的线程池中同步执行函数（异步兼容）."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(sync_func, *args)
            return future.result()
    return sync_func(*args)


def validate_path(root: str) -> str:
    """验证路径安全，返回规范化后的字符串。无 body 场景替代 validate_project_root."""
    from .errors import PathTraversalError, ValidationError

    if not root or not root.strip():
        raise ValidationError("root path is required")
    path = Path(root).resolve()
    if ".." in str(path):
        raise PathTraversalError(f"Path traversal detected: {root}")
    if not path.is_absolute():
        raise ValidationError(f"Path must be absolute: {root}")
    return str(path)

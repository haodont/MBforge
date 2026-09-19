"""MBForge fixed model backends — local inference package.

Provides lazy-loading wrappers for the heavyweight local models used by the
pipeline (MolParser-Mobile for chemical structure recognition and MolDetv2
for molecule detection), plus shared path resolution through the
ResourceManager.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.utils.logger import get_logger

from . import (
    molparser,  # noqa: F401
)

logger = get_logger(__name__)

# 模型名 → RESOURCE_CATALOG id 的映射
_MODEL_NAME_TO_RESOURCE_ID = {
    "UniParser/MolDetv2": "moldet",
    "MolDetv2": "moldet",
    "moldetv2": "moldet",
    "UniParser/MolParser-Mobile": "molparser",
    "MolParser": "molparser",
    "molparser": "molparser",
    "PatSnap/Hiro-Layout": "hiro_layout",
    "Hiro-Layout": "hiro_layout",
    "hiro_layout": "hiro_layout",
}


def resolve_model_path(model_name: str, cache_name: str | None = None) -> str:
    """解析模型路径 — 统一走 ResourceManager.

    ResourceManager 是路径解析的唯一真相源（基于 constants.yaml + 用户 settings）。
    """
    p = Path(model_name)
    if p.is_absolute() or (p.exists() and p.is_dir()):
        return str(model_name)

    from mbforge.infra.resource_manager import (
        ResourceManager,
        _read_resolved_paths,
    )

    resolved = _read_resolved_paths()
    rid = cache_name or model_name
    for prefix, mapped in _MODEL_NAME_TO_RESOURCE_ID.items():
        if prefix.lower() in rid.lower():
            path = ResourceManager.resolve_model_for_backend(mapped)
            if path is not None:
                logger.info(f"Resolved {rid} → {path} (via ResourceManager)")
                return str(path)
            if resolved and mapped in resolved:
                rpath = resolved[mapped]
                if Path(rpath).exists():
                    logger.info(f"Resolved {rid} → {rpath} (via resolved_paths)")
                    return rpath

    logger.info(f"No cached path for {model_name}")
    return model_name

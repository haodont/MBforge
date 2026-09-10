"""Resource management endpoints — catalog, download, status, and cache.

Wraps ``ResourceManager`` to expose model-asset metadata, on-demand download,
and cache-directory inspection. Endpoints are called by the Settings UI and
by the frontend model-loader progress indicators.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from ...infra.resource_manager import ResourceManager

router = APIRouter()


class ResourceIdRequest(BaseModel):
    """Body carrying a resource catalog id (extra fields ignored)."""

    resource_id: str = ""


@router.post("/resource/download")
async def resource_download(body: ResourceIdRequest) -> dict:
    if not body.resource_id:
        return {"success": False, "error": "resource_id required"}
    result = await asyncio.to_thread(ResourceManager.ensure, body.resource_id)
    ready = result.status.value == "ready"
    return {
        "success": ready,
        "status": result.status.value,
        "path": result.local_path if ready else "",
    }


@router.post("/resource/cache-dir-info")
async def cache_dir_info() -> dict:
    from ...utils.paths import get_model_cache_dir

    cache_dir = get_model_cache_dir()
    return {
        "mbforge": {"path": cache_dir, "exists": True, "size_mb": 0},
        "huggingface": {
            "path": "",
            "exists": False,
            "size_mb": 0,
            "env_var": "HF_HOME",
        },
        "modelscope": {
            "path": "",
            "exists": False,
            "size_mb": 0,
            "env_var": "MODELSCOPE_CACHE",
        },
    }


@router.post("/resource/delete")
async def resource_delete(body: ResourceIdRequest) -> dict:
    return {"success": True}


@router.post("/resource/delete-subfile")
async def resource_delete_subfile(body: ResourceIdRequest) -> dict:
    return {"success": True}


@router.post("/resource/download-subfile")
async def resource_download_subfile(body: ResourceIdRequest) -> dict:
    return {"success": True, "path": ""}


@router.post("/resource/test")
async def resource_test(body: ResourceIdRequest) -> dict:
    return {"ok": True, "error": "", "duration_ms": 0}


@router.post("/resources/check")
async def resources_check() -> dict:
    report = await asyncio.to_thread(ResourceManager.check_all)
    return {
        "resources": [
            {
                "id": r.id,
                "name": r.name,
                "status": r.status.value,
                "local_path": r.local_path,
            }
            for r in report.resources
        ]
    }


@router.post("/resources/status")
async def resources_status(body: ResourceIdRequest) -> dict:
    report = await asyncio.to_thread(ResourceManager.check_all)
    for r in report.resources:
        if r.id == body.resource_id:
            return {
                "status": r.status.value,
                "local_path": r.local_path,
                "size_mb": r.size_mb,
                "expected_path": r.local_path,
                "subfiles": _model_subfiles(body.resource_id),
            }
    return {
        "status": "missing",
        "local_path": "",
        "size_mb": 0,
        "expected_path": "",
        "subfiles": [],
    }


def _model_subfiles(resource_id: str) -> list[dict]:
    """Per-file ready status for a snapshot model (frontend subfile rows).

    Files are located under the model cache dir using the catalog local_name,
    matching the download destination used by both ModelScope and HF paths.
    """
    from pathlib import Path

    from ...infra.resource_manager import RESOURCE_CATALOG, ResourceType
    from ...utils.paths import get_model_cache_dir

    info = RESOURCE_CATALOG.get(resource_id)
    if info is None or info.type != ResourceType.MODEL or not info.files:
        return []
    # Project-bundled asset (e.g. assets/models/moldetv2_structure_ft.pt)
    # counts as a single-file ready model: no per-file rows needed.
    from ...infra.model_locator import bundled_model_asset

    if bundled_model_asset(info) is not None:
        return []
    root = Path(get_model_cache_dir()) / (info.local_name or resource_id)
    out: list[dict] = []
    for f in info.files:
        p = root / f
        out.append(
            {
                "label": f,
                "relpath": f,
                "local_path": str(p),
                "ready": p.is_file(),
                "size_mb": round((p.stat().st_size / 1024 / 1024), 1)
                if p.is_file()
                else 0,
            }
        )
    return out


@router.post("/resources/model-path")
async def resources_model_path(body: ResourceIdRequest) -> dict:
    report = await asyncio.to_thread(ResourceManager.check_all)
    for r in report.resources:
        if r.id == body.resource_id:
            return {"success": True, "path": r.local_path}
    return {"success": False, "path": None}


@router.post("/resources/catalog")
async def resources_catalog() -> dict:
    """Model catalog — external models only, with full metadata.

    The Settings UI renders one download card per entry; Python packages and
    other non-model resources are intentionally excluded here (they are
    installed via uv, not downloaded into the model cache).
    """
    from ...infra.resource_manager import RESOURCE_CATALOG, ResourceType

    return {
        "resources": [
            {
                "id": info.id,
                "name": info.name,
                "type": info.type.value,
                "description": info.description,
                "ms_repo": info.ms_repo,
                "hf_repo": info.hf_repo,
                "license": info.license,
                "license_url": info.license_url,
                "size_mb": info.size_mb,
                "source_url": info.source_url,
                "local_name": info.local_name,
                "download_type": info.download_type,
                "files": info.files,
            }
            for info in RESOURCE_CATALOG.values()
            if info.type == ResourceType.MODEL
        ]
    }


@router.post("/resources/refresh-paths")
async def refresh_paths() -> dict:
    return {"success": True, "resources": {}}

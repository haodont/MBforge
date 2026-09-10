"""Health check and sidecar status endpoints.

Probes local model backends (MolDet, MolParser) and reports their readiness.
Used by the frontend status bar and by external load balancers to decide
whether the sidecar is ready to serve traffic.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from ...infra.resource_manager import ResourceManager

router = APIRouter()


def _moldet_status() -> str:
    """moldet: status from ResourceManager (covers FT detector + download state)."""
    try:
        return ResourceManager.check("moldet").status.value
    except Exception:
        return "error"


def _molparser_status() -> str:
    """molparser: backend.health() reports the recognizer readiness."""
    try:
        from ...backends import molparser

        return molparser.health().get("status", "unknown")
    except Exception:
        return "error"


@router.get("/health")
async def health() -> dict:
    statuses = {
        "moldet": await asyncio.to_thread(_moldet_status),
        "molparser": await asyncio.to_thread(_molparser_status),
    }
    overall = "online" if all(s == "ready" for s in statuses.values()) else "partial"
    return {"status": overall, "models": statuses, "resources": {}}


@router.get("/sidecar/status")
async def sidecar_status() -> dict:
    report = await asyncio.to_thread(ResourceManager.check_all)
    # Reuse the check_all report instead of re-scanning moldet via health().
    moldet = next((r for r in report.resources if r.id == "moldet"), None)
    return {
        "healthy": all(r.status.value == "ready" for r in report.resources),
        "state": "online",
        "restart_count": 0,
        "uptime_secs": 0,
        "last_error": None,
        "models": {
            "moldet": moldet.status.value if moldet is not None else "error",
            "molparser": _molparser_status(),
        },
    }


@router.post("/sidecar/restart")
async def sidecar_restart() -> dict:
    """Sidecar restart stub (not needed in pure web mode)."""
    return {"success": True}


@router.get("/environment/check")
async def environment_check() -> dict:
    report = await asyncio.to_thread(ResourceManager.check_all)
    return {
        "python_version": report.python_version,
        "gpu_available": report.gpu_available,
        "gpu_name": report.gpu_name,
        "cuda_version": report.cuda_version,
        "resources": [
            {
                "id": r.id,
                "name": r.name,
                "status": r.status.value,
                "local_path": r.local_path,
                "size_mb": r.size_mb,
            }
            for r in report.resources
        ],
    }

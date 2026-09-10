"""Local model testing and management endpoints (thin HTTP surface).

Lifecycle logic (loaded-state / unload / smoke test) lives in
:mod:`mbforge.infra.models`; molecule rendering lives in
:mod:`mbforge.services.chem.chem`. These endpoints run against in-process
model singletons; they do not start external workers.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from ...infra import models as models_infra
from ...models.common import (
    ModelTestRequest,
    ModelTestResponse,
    MoleculeRenderRequest,
    MoleculeRenderResponse,
)
from ...services.chem import chem as chem_service
from ...utils.logger import get_logger

logger = get_logger("mbforge.routers.models")

router = APIRouter()


class ClearCacheRequest(BaseModel):
    """Body for POST /clear-cache (extra fields ignored)."""

    model_id: str | None = None


@router.get("/loaded-status")
async def loaded_status() -> dict:
    """Return loaded local model state and process RSS memory."""
    return await asyncio.to_thread(models_infra.loaded)


@router.post("/clear-cache")
async def clear_cache(body: ClearCacheRequest) -> dict:
    """Unload local models; downloaded weight files are retained."""
    return await asyncio.to_thread(models_infra.clear, body.model_id)


@router.post("/test")
async def test_model(body: ModelTestRequest) -> ModelTestResponse:
    """Test a model by loading and running inference."""
    result = await asyncio.to_thread(models_infra.test, body.model_id, body.subpath)
    return ModelTestResponse(**result)


@router.post("/mol/render")
async def render_molecule(body: MoleculeRenderRequest) -> MoleculeRenderResponse:
    """Render a molecule to SVG/PNG."""
    if not body.smiles:
        return MoleculeRenderResponse(error="smiles required")

    result = await asyncio.to_thread(
        chem_service.render_molecule_png_sync,
        body.smiles,
        body.width or 300,
        body.height or 200,
    )
    return MoleculeRenderResponse(**result)

"""SAR (Structure-Activity Relationship) endpoints — fail-closed stubs.

The R-group matrix builder and activity heatmap are implemented as
fail-closed stubs: ``build-matrix`` returns success:false so the FE does
not treat empty matrices as real results, and ``heatmap`` may only be
invoked after a successful build-matrix (which is the gate that fails
closed).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import AliasChoices, BaseModel, Field

router = APIRouter()


class SarBuildMatrixRequest(BaseModel):
    """Body for the R-group matrix stub; ``coreSmiles`` is the legacy key."""

    core_smiles: str = Field(
        default="", validation_alias=AliasChoices("coreSmiles", "core_smiles")
    )


@router.post("/build-matrix")
async def build_matrix(body: SarBuildMatrixRequest) -> dict:
    """Build R-group matrix — not implemented."""
    return {
        "success": False,
        "error": "SAR analysis is not implemented yet.",
        "core_smiles": body.core_smiles,
        "r_labels": [],
        "rows": [],
        "compounds": [],
        "unmatched_count": 0,
    }


class SarHeatmapRequest(BaseModel):
    """Empty stub body; extra fields ignored."""


@router.post("/heatmap")
async def heatmap(body: SarHeatmapRequest) -> list:
    """Activity heatmap — not implemented; empty list + no success flag.

    Callers must only invoke after a successful build-matrix. Returning an
    empty list (not a fake success envelope) keeps FE ``ActivityHeatmap[]``
    typing; build-matrix is the gate that fails closed.
    """
    return []

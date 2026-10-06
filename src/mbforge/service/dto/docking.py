"""Pydantic models for the docking endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DockingBoxModel(BaseModel):
    """Search box: center and size (Ångström), each three numbers."""

    center: list[float] = Field(..., min_length=3, max_length=3)
    size: list[float] = Field(..., min_length=3, max_length=3)


class DockingLigandModel(BaseModel):
    """One ligand: a library molecule id and/or a SMILES string."""

    label: str = Field("", max_length=256)
    smiles: str = Field("", max_length=2048)
    mol_id: str | None = Field(None, max_length=2048)


class DockingJobRequest(BaseModel):
    """Body for creating a docking job."""

    library_root: str | None = None
    receptor_id: str = Field(..., min_length=1, max_length=128)
    ligands: list[DockingLigandModel] = Field(..., min_length=1, max_length=500)
    box: DockingBoxModel
    params: dict[str, Any] = Field(default_factory=dict)


class DockingJobListResponse(BaseModel):
    success: bool = True
    jobs: list[dict] = Field(default_factory=list)


class DockingJobResponse(BaseModel):
    success: bool = True
    job: dict = Field(default_factory=dict)


class ReceptorListResponse(BaseModel):
    success: bool = True
    receptors: list[dict] = Field(default_factory=list)


class ReceptorResponse(BaseModel):
    success: bool = True
    receptor: dict = Field(default_factory=dict)


class EngineStatusResponse(BaseModel):
    success: bool = True
    ready: bool = False
    engine: str = ""
    reason: str = ""

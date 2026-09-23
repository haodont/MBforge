"""Pydantic models for the detection-cache router.

Schemas for persisting, retrieving, and clearing cached molecule
detections extracted from PDF pages during the ingestion pipeline.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from mbforge.application.dto.common import LibraryRootMixin as _LibraryRootMixin


class DetectionInput(BaseModel):
    """Single detection row accepted by ``POST /api/v1/detection-cache/save``."""

    model_config = ConfigDict(extra="ignore")

    mol_id: str | None = Field(None, description="Molecule identifier (may be null)")
    doc_id: str = Field(..., description="Document identifier")
    page: int = Field(..., description="Page number")
    bbox_x0: float | None = Field(None, description="BBox left")
    bbox_y0: float | None = Field(None, description="BBox top")
    bbox_x1: float | None = Field(None, description="BBox right")
    bbox_y1: float | None = Field(None, description="BBox bottom")
    crop_relpath: str | None = Field(None, description="Path to cropped image")
    conf_moldet: float | None = Field(None, description="MolDet confidence")
    vlm_verified_esmiles: str | None = Field(
        None,
        validation_alias=AliasChoices("vlm_verified_esmiles", "esmiles", "smiles"),
        description="Verified E-SMILES / SMILES string",
    )


class DetectionGetRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/detection-cache/get``."""

    doc_id: str = Field(
        ...,
        validation_alias=AliasChoices("doc_id", "docId"),
        description="Document identifier",
    )
    page: int = Field(0, description="Page number")


class DetectionExtractPageRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/detection-cache/extract-page``."""

    doc_id: str = Field(
        ...,
        validation_alias=AliasChoices("doc_id", "docId"),
        description="Document identifier",
    )
    page: int = Field(0, description="Page number")


class DetectionSaveRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/detection-cache/save``."""

    detections: list[DetectionInput] = Field(
        default_factory=list, description="Detection rows to persist"
    )


class DetectionStatsRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/detection-cache/stats``."""


class DetectionClearRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/detection-cache/clear``."""


class DetectionClearDocRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/detection-cache/clear-doc``."""

    doc_id: str = Field(
        ...,
        validation_alias=AliasChoices("doc_id", "docId"),
        description="Document identifier",
    )


class DetectionBatchScanRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/detection-cache/batch-scan``."""

    doc_ids: list[str] = Field(default_factory=list, description="Document IDs")


class DetectionResult(BaseModel):
    """Single detection result returned by cache read endpoints."""

    evidence_id: str | None = None
    esmiles: str | None = ""
    # Layer-1 pure SMILES (RDKit-renderable); empty for legacy cache rows.
    smiles: str | None = ""
    name: str | None = ""
    source: str = "image"
    moldet_conf: float = 0.0
    bbox_pdf: list[float] = Field(default_factory=list)
    page_idx: int | None = 0
    context_text: str = ""
    mol_img_path: str | None = None
    status: str = "pending"
    properties: dict = Field(default_factory=dict)
    # Raw SQL-shaped fields kept for callers that expect the row layout.
    mol_id: str | None = None
    doc_id: str | None = None
    page: int | None = None
    bbox_x0: float | None = 0.0
    bbox_y0: float | None = 0.0
    bbox_x1: float | None = 0.0
    bbox_y1: float | None = 0.0
    crop_relpath: str | None = None
    conf_moldet: float | None = 0.0


class CachedDetectionsResponse(BaseModel):
    """Response body for cache read endpoints."""

    success: bool = True
    results: list[DetectionResult] = Field(default_factory=list)
    detections: list[DetectionResult] = Field(default_factory=list)
    count: int = 0
    source: str = "cache_miss"
    cache_path: str | None = None


class SaveResponse(BaseModel):
    """Response body for ``POST /api/v1/detection-cache/save``."""

    success: bool = True
    error: str | None = None


class StatsResponse(BaseModel):
    """Response body for ``POST /api/v1/detection-cache/stats``."""

    disk_usage_bytes: int = 0
    cached_page_count: int = 0
    cached_doc_count: int = 0
    schema_version: int = 1


class ClearResponse(BaseModel):
    """Response body for clear / clear-doc endpoints."""

    success: bool = True
    cleared: int = 0


class BatchScanResponse(BaseModel):
    """Response body for ``POST /api/v1/detection-cache/batch-scan``."""

    success: bool = False
    error: str = "batch-scan not implemented; use /api/v1/moldet/extract-pdf per page"
    results: list = Field(default_factory=list)
    processed: int = 0
    total: int = 0
    errors: list[str] = Field(default_factory=lambda: ["not_implemented"])

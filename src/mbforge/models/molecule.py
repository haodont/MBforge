"""Pydantic models for the molecule catalog API.

Request and response schemas for searching, filtering, creating, updating,
and bulk-managing molecules in the MBForge library.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---- Request models ----


class MoleculeListRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(50, ge=1, le=10000, description="Items per page")
    status: str = Field("", description="Filter by status")
    source_type: str = Field("", description="Filter by source type")
    source_doc: str = Field("", description="Filter by source document")
    activity_presence: str = Field("all", description="Filter by activity presence")
    activity_min: float | None = Field(None, description="Minimum activity")
    activity_max: float | None = Field(None, description="Maximum activity")
    query: str = Field("", description="Text search query")
    sort_field: str = Field("created_at", description="Sort field")
    sort_direction: str = Field("desc", description="Sort direction")


class MoleculeSearchRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    query: str = Field(..., description="Search query")
    mode: Literal["auto", "text", "substructure", "similarity"] = Field(
        "auto", description="Search mode: auto/text/substructure/similarity"
    )
    top_k: int = Field(20, ge=1, le=1000, description="Max results")
    similarity_threshold: float = Field(
        0.5, ge=0.0, le=1.0, description="Minimum Tanimoto similarity"
    )


class MoleculeGetRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    mol_id: str = Field(..., description="Molecule ID")


class MoleculeCreateRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    smiles: str = Field(..., description="SMILES string")
    mol_id: str | None = Field(
        None, description="Molecule ID (auto-generated if omitted)"
    )
    esmiles: str = Field("", description="Extended SMILES")
    name: str = Field("", description="Molecule name")
    source_type: str = Field("manual", description="Source type")


class MoleculeUpdateRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    smiles: str | None = None
    name: str | None = None
    esmiles: str | None = None
    activity: float | None = None
    activity_type: str | None = None
    units: str | None = None
    status: str | None = None
    notes: str | None = None
    labels: list[str] | None = None
    # The frontend uses ``tags`` for the DB ``labels`` column.
    tags: list[str] | None = None
    properties: dict | None = None


class MoleculeBulkStatusRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    mol_ids: list[str] = Field(..., min_length=1, max_length=10000)
    status: str = Field(..., min_length=1)


class MoleculeDeleteRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")


class MoleculeBulkDeleteRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    mol_ids: list[str] = Field(..., min_length=1, max_length=10000)


class MoleculeStatsRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")


class MoleculeEvidenceRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    canonical_smiles: str = Field(..., description="Canonical SMILES or mol_id")


# ---- Response models ----


class MoleculeListResponse(BaseModel):
    success: bool = True
    items: list[dict] = []
    total: int = 0
    matching_ids: list[str] = []
    source_types: list[str] = []
    source_docs: list[str] = []
    # Set when matching_ids was truncated to avoid pulling 100k+ ids
    # into a single list response. UI should fall back to per-page
    # selection when this is true.
    truncated: bool = False


class MoleculeSearchResponse(BaseModel):
    success: bool = True
    results: list[dict] = []


class MoleculeGetResponse(BaseModel):
    success: bool = True
    molecule: dict | None = None


class MoleculeEvidenceResponse(BaseModel):
    success: bool = True
    molecule: dict | None = None
    evidence: list[dict] = []


class MoleculeLocationBBox(BaseModel):
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None


class MoleculeLocationMatch(BaseModel):
    mol_id: str | None = None
    canonical_smiles: str = ""
    name: str = ""
    confidence: float | None = None
    page: int
    bbox: MoleculeLocationBBox | None = None
    crop_url: str | None = None


class MoleculeByLocationResponse(BaseModel):
    success: bool = True
    matches: list[MoleculeLocationMatch] = Field(default_factory=list)


class MoleculeCorrectionsResponse(BaseModel):
    success: bool = True
    corrections: list[dict] = Field(default_factory=list)


class MoleculeCreateResponse(BaseModel):
    success: bool = True
    mol_id: str = ""


class MoleculeUpdateResponse(BaseModel):
    success: bool = True


class MoleculeBulkStatusResponse(BaseModel):
    success: bool = True
    updated: int = 0
    skipped: int = 0


class MoleculeDeleteResponse(BaseModel):
    success: bool = True
    deleted: int = 0


class MoleculeStatsResponse(BaseModel):
    success: bool = True
    total: int = 0
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}


class MoleculeRecorrectRequest(BaseModel):
    library_root: str | None = None
    doc_id: str | None = None
    dry_run: bool = True


class MoleculeRecorrectResponse(BaseModel):
    success: bool = True
    total_molecules: int = 0
    corrected_count: int = 0
    flagged_count: int = 0
    corrections: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

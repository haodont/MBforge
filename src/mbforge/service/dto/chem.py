"""Pydantic models for the chemistry router.

Schemas for SMILES validation, fingerprinting, Tanimoto similarity,
image rendering, Markush parsing, and R-group operations.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field, model_validator


class SmilesRequest(BaseModel):
    """Request body for endpoints that operate on a single SMILES string."""

    smiles: str = Field(
        ...,
        validation_alias=AliasChoices("smiles", "input", "raw"),
        description="SMILES notation of the molecule",
    )


class FingerprintPairRequest(BaseModel):
    """Request body for the Tanimoto similarity endpoint."""

    fingerprint_a: list[int] = Field(
        ...,
        validation_alias=AliasChoices("fingerprint_a", "smiles_a"),
        description="First fingerprint bits",
    )
    fingerprint_b: list[int] = Field(
        ...,
        validation_alias=AliasChoices("fingerprint_b", "smiles_b"),
        description="Second fingerprint bits",
    )


class SmilesImageRequest(BaseModel):
    """Request body for the SMILES-to-SVG endpoint."""

    smiles: str = Field(..., description="SMILES notation of the molecule")
    width: int = Field(360, ge=120, le=1000, description="Image width in pixels")
    height: int = Field(240, ge=120, le=1000, description="Image height in pixels")


class ValidateSmilesRequest(BaseModel):
    """Request body for batch SMILES validation.

    Accepts either ``list`` for batch validation or ``smiles`` for single-item
    legacy validation.
    """

    smiles_list: list[str] | None = Field(
        None,
        validation_alias=AliasChoices("list", "smiles_list"),
        description="Batch of SMILES strings",
    )
    smiles: str | None = Field(None, description="Single SMILES string (legacy)")

    @model_validator(mode="after")
    def _check_at_least_one(self) -> ValidateSmilesRequest:
        if not self.smiles_list and not self.smiles:
            raise ValueError("list or smiles required")
        return self


class ValidateSmilesResponse(BaseModel):
    """Response body for a single SMILES validation result."""

    input: str = Field("", description="Original SMILES input")
    valid: bool = False
    canonical_smiles: str | None = Field(None, description="Canonical SMILES if valid")
    smiles: str = Field("", description="Original SMILES input (legacy field)")
    error: str | None = None


class FingerprintResponse(BaseModel):
    """Response body for ``/api/v1/chem/fingerprint``."""

    success: bool = True
    fingerprint: list[int] = Field(default_factory=list)
    bits: int = 0
    error: str | None = None


class TanimotoResponse(BaseModel):
    """Response body for ``/api/v1/chem/tanimoto``."""

    success: bool = True
    similarity: float = 0.0
    error: str | None = None


class MoleculeProperties(BaseModel):
    """Computed molecular properties."""

    molecular_weight: float = 0.0
    logp: float = 0.0
    hbd: int = 0
    hba: int = 0
    tpsa: float = 0.0
    rotatable_bonds: int = 0
    aromatic_rings: int = 0
    formula: str = ""


class PropertiesResponse(BaseModel):
    """Response body for ``/api/v1/chem/properties``."""

    success: bool = True
    properties: MoleculeProperties | None = None
    error: str | None = None


class CanonicalizeResponse(BaseModel):
    """Response body for ``/api/v1/chem/canonicalize``."""

    success: bool = True
    result: str = ""
    error: str | None = None


class SmilesImageResponse(BaseModel):
    """Response body for ``/api/v1/chem/smiles-to-image``."""

    success: bool = True
    svg: str = ""
    error: str | None = None


class EsTag(BaseModel):
    """E-SMILES tag representation."""

    kind: str = ""
    index: int = 0
    value: str = ""


class EsTagRequest(BaseModel):
    """Request body for the SMILES-to-E-SMILES endpoint."""

    smiles: str = Field(..., description="Base SMILES string")
    tags: list[EsTag] = Field(default_factory=list, description="E-SMILES tags")


class EsTagParseResponse(BaseModel):
    """Response body for ``/api/v1/chem/parse-esmiles-tags``."""

    success: bool = True
    smiles: str = ""
    tags: list[EsTag] = Field(default_factory=list)
    error: str | None = None


class LayerSplitResponse(BaseModel):
    """Response body for ``/api/v1/chem/separate-esmiles-layers``."""

    success: bool = True
    smiles: str = ""
    esmiles: str | None = None
    tags: list[EsTag] | None = None
    error: str | None = None


class MarkushRGroup(BaseModel):
    """R-group definition inside a Markush pattern."""

    atom_index: int = 0
    group_name: str = ""
    definition: dict = Field(default_factory=dict)


class MarkushRing(BaseModel):
    """Abstract ring in a Markush pattern."""

    index: int = 0
    name: str = ""


class MarkushPatternResponse(BaseModel):
    """Response body for ``/api/v1/chem/markush-parse``."""

    success: bool = True
    core_smiles: str = ""
    r_groups: list[MarkushRGroup] = Field(default_factory=list)
    abstract_rings: list[MarkushRing] = Field(default_factory=list)
    raw: str = ""
    error: str | None = None


class MarkushCheckRequest(BaseModel):
    """Request body for ``/api/v1/chem/markush-check``."""

    esmiles: str = Field(..., description="E-SMILES / Markush string")
    query: str = Field(..., description="Query SMILES")
    ctx: str | None = Field(None, description="Optional context SMILES")


class RGroupResult(BaseModel):
    """Single R-group overlap result."""

    group_name: str = ""
    position: int = 0
    query_substituent: str | None = None
    within_scope: bool | None = None
    definition: str = ""


class MarkushOverlapResponse(BaseModel):
    """Response body for ``/api/v1/chem/markush-check``."""

    success: bool = True
    match_level: str = "NoOverlap"
    core_overlap_ratio: float = 0.0
    matched_core_atoms: int = 0
    total_core_atoms: int = 0
    r_group_results: list[RGroupResult] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)
    error: str | None = None


class SubstructureSearchRequest(BaseModel):
    """Request body for ``/api/v1/chem/substructure-search``."""

    query: str = Field(..., description="Query SMILES")
    candidates: list = Field(default_factory=list, description="Candidate molecules")
    threshold: float = Field(0.5, ge=0.0, le=1.0, description="Similarity threshold")
    library_root: str | None = Field(None, description="Project root directory")
    top_k: int = Field(100, ge=1, le=1000, description="Max results")


class SubstructureSearchResponse(BaseModel):
    """Response body for ``/api/v1/chem/substructure-search``."""

    success: bool = True
    results: list = Field(default_factory=list)
    error: str | None = None


class SimilaritySearchRequest(BaseModel):
    """Request body for ``/api/v1/chem/similarity-search``."""

    query: str = Field(..., description="Query SMILES")
    candidates: list = Field(default_factory=list, description="Candidate molecules")
    library_root: str | None = Field(None, description="Project root directory")
    top_k: int = Field(100, ge=1, le=1000, description="Max results")
    threshold: float = Field(
        0.5, ge=0.0, le=1.0, description="Minimum Tanimoto similarity"
    )


class SimilaritySearchResponse(BaseModel):
    """Response body for ``/api/v1/chem/similarity-search``."""

    success: bool = True
    results: list = Field(default_factory=list)
    error: str | None = None


class GesimAtomMappingRequest(BaseModel):
    """Request body for ``/api/v1/chem/gesim-atom-mapping``."""

    smiles_a: str = Field(
        ...,
        validation_alias=AliasChoices("a", "smiles_a"),
        description="First SMILES string",
    )
    smiles_b: str = Field(
        ...,
        validation_alias=AliasChoices("b", "smiles_b"),
        description="Second SMILES string",
    )


class AtomMappingResponse(BaseModel):
    """Response body for ``/api/v1/chem/gesim-atom-mapping``."""

    success: bool = True
    mapping_a: list[int | None] = Field(default_factory=list)
    mapping_b: list[int | None] = Field(default_factory=list)
    error: str | None = None


class RGroupNameRequest(BaseModel):
    """Request body for ``/api/v1/chem/preprocess-rgroup-name``."""

    name: str = Field(
        ...,
        validation_alias=AliasChoices("name", "smiles"),
        description="R-group name to preprocess",
    )

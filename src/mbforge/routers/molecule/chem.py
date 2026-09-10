"""Chemistry operation endpoints — thin async shells.

All RDKit logic lives in :mod:`mbforge.services.chem.chem`; this router
only validates requests, delegates to the service on a worker thread,
and shapes unimplemented-endpoint stubs.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from ...models.chem import (
    AtomMappingResponse,
    CanonicalizeResponse,
    EsTagParseResponse,
    FingerprintPairRequest,
    FingerprintResponse,
    GesimAtomMappingRequest,
    LayerSplitResponse,
    MarkushCheckRequest,
    MarkushOverlapResponse,
    MarkushPatternResponse,
    PropertiesResponse,
    SimilaritySearchRequest,
    SimilaritySearchResponse,
    SmilesImageRequest,
    SmilesImageResponse,
    SmilesRequest,
    SubstructureSearchRequest,
    SubstructureSearchResponse,
    TanimotoResponse,
    ValidateSmilesRequest,
    ValidateSmilesResponse,
)
from ...services.chem import chem as chem_service

router = APIRouter()


@router.post("/validate-smiles", response_model=list[ValidateSmilesResponse])
async def validate_smiles(body: ValidateSmilesRequest) -> list[ValidateSmilesResponse]:
    """Batch validate SMILES strings.

    Accepts either ``{"list": ["CCO", ...]}`` for batch validation or
    ``{"smiles": "CCO"}`` for single-item validation (legacy).
    """
    items = list(body.smiles_list) if body.smiles_list else []
    if body.smiles is not None:
        items = [body.smiles]
    return await asyncio.to_thread(chem_service.validate_smiles_sync, items)


@router.post("/fingerprint", response_model=FingerprintResponse)
async def fingerprint(body: SmilesRequest) -> FingerprintResponse:
    return await asyncio.to_thread(chem_service.fingerprint_sync, body.smiles)


@router.post("/tanimoto", response_model=TanimotoResponse)
async def tanimoto(body: FingerprintPairRequest) -> TanimotoResponse:
    return await asyncio.to_thread(
        chem_service.tanimoto_sync, body.fingerprint_a, body.fingerprint_b
    )


@router.post("/properties", response_model=PropertiesResponse)
async def properties(body: SmilesRequest) -> PropertiesResponse:
    return await asyncio.to_thread(chem_service.properties_sync, body.smiles)


@router.post("/canonicalize", response_model=CanonicalizeResponse)
async def canonicalize(body: SmilesRequest) -> CanonicalizeResponse:
    return await asyncio.to_thread(chem_service.canonicalize_sync, body.smiles)


@router.post("/smiles-to-image", response_model=SmilesImageResponse)
async def smiles_to_image(body: SmilesImageRequest) -> SmilesImageResponse:
    """Render SMILES, including Markush wildcard atoms, to an SVG image."""
    return await asyncio.to_thread(
        chem_service.draw_smiles_sync, body.smiles, body.width, body.height
    )


@router.post("/core-smiles", response_model=CanonicalizeResponse)
async def core_smiles(body: SmilesRequest) -> CanonicalizeResponse:
    """Extract core SMILES from E-SMILES — not implemented."""
    return CanonicalizeResponse(
        success=False, error="core-smiles not implemented", result=""
    )


@router.post("/smiles-to-esmiles", response_model=CanonicalizeResponse)
async def smiles_to_esmiles(body: SmilesRequest) -> CanonicalizeResponse:
    """SMILES to E-SMILES — not implemented (passthrough would lie)."""
    return CanonicalizeResponse(
        success=False, error="smiles-to-esmiles not implemented", result=""
    )


@router.post("/parse-esmiles-tags", response_model=EsTagParseResponse)
async def parse_esmiles_tags(body: SmilesRequest) -> EsTagParseResponse:
    """Parse E-SMILES tags — not implemented."""
    return EsTagParseResponse(
        success=False,
        error="parse-esmiles-tags not implemented",
        smiles="",
        tags=[],
    )


@router.post("/sanitize-esmiles", response_model=CanonicalizeResponse)
async def sanitize_esmiles(body: SmilesRequest) -> CanonicalizeResponse:
    """Sanitize E-SMILES — not implemented."""
    return CanonicalizeResponse(
        success=False, error="sanitize-esmiles not implemented", result=""
    )


@router.post("/separate-esmiles-layers", response_model=LayerSplitResponse)
async def separate_esmiles_layers(body: SmilesRequest) -> LayerSplitResponse:
    """Separate E-SMILES layers — not implemented."""
    return LayerSplitResponse(
        success=False,
        error="separate-esmiles-layers not implemented",
        smiles="",
        esmiles=None,
        tags=None,
    )


@router.post("/preprocess-smiles", response_model=CanonicalizeResponse)
async def preprocess_smiles(body: SmilesRequest) -> CanonicalizeResponse:
    """Preprocess SMILES — not implemented."""
    return CanonicalizeResponse(
        success=False, error="preprocess-smiles not implemented", result=""
    )


@router.post("/preprocess-rgroup-name", response_model=CanonicalizeResponse)
async def preprocess_rgroup_name(body: SmilesRequest) -> CanonicalizeResponse:
    """Preprocess R-group name — not implemented."""
    return CanonicalizeResponse(
        success=False, error="preprocess-rgroup-name not implemented", result=""
    )


@router.post("/markush-parse", response_model=MarkushPatternResponse)
async def markush_parse(body: SmilesRequest) -> MarkushPatternResponse:
    """Parse a Markush SMILES into the core + explicit attachment sites."""
    try:
        result = await asyncio.to_thread(chem_service.markush_parse_sync, body.smiles)
    except Exception as exc:  # noqa: BLE001
        return MarkushPatternResponse(
            success=False,
            error=f"markush-parse failed: {exc}",
            core_smiles="",
            r_groups=[],
            abstract_rings=[],
            raw=body.smiles,
        )
    return MarkushPatternResponse(**result)


@router.post("/markush-check", response_model=MarkushOverlapResponse)
async def markush_check(body: MarkushCheckRequest) -> MarkushOverlapResponse:
    """Check whether *query* falls within a Markush pattern's scope."""
    try:
        result = await asyncio.to_thread(
            chem_service.markush_check_sync, body.esmiles, body.query
        )
    except Exception as exc:  # noqa: BLE001
        return MarkushOverlapResponse(
            success=False,
            error=f"markush-check failed: {exc}",
            match_level="NoOverlap",
            core_overlap_ratio=0.0,
            matched_core_atoms=0,
            total_core_atoms=0,
            r_group_results=[],
            details=[],
        )
    return MarkushOverlapResponse(**result)


@router.post("/substructure-search", response_model=SubstructureSearchResponse)
async def substructure_search(
    body: SubstructureSearchRequest,
) -> SubstructureSearchResponse:
    return await asyncio.to_thread(chem_service.substructure_search_sync, body)


@router.post("/similarity-search", response_model=SimilaritySearchResponse)
async def similarity_search(
    body: SimilaritySearchRequest,
) -> SimilaritySearchResponse:
    return await asyncio.to_thread(chem_service.similarity_search_sync, body)


@router.post("/gesim-atom-mapping", response_model=AtomMappingResponse)
async def gesim_atom_mapping(body: GesimAtomMappingRequest) -> AtomMappingResponse:
    """GESim atom mapping — not implemented."""
    return AtomMappingResponse(
        success=False,
        error="gesim-atom-mapping not implemented",
        mapping_a=[],
        mapping_b=[],
    )

"""Molecule CRUD endpoints.

Exposes create, read, update, and delete operations for the ``molecules``
table, plus search, evidence-chain lookup, and statistics. All endpoints
resolve ``library_root`` from the request body or the stored default and
delegate to :mod:`mbforge.services.molecule.queries`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from ...models.molecule import (
    MoleculeBulkDeleteRequest,
    MoleculeBulkStatusRequest,
    MoleculeBulkStatusResponse,
    MoleculeByLocationResponse,
    MoleculeCorrectionsResponse,
    MoleculeCreateRequest,
    MoleculeCreateResponse,
    MoleculeDeleteRequest,
    MoleculeDeleteResponse,
    MoleculeEvidenceRequest,
    MoleculeEvidenceResponse,
    MoleculeGetRequest,
    MoleculeGetResponse,
    MoleculeListRequest,
    MoleculeListResponse,
    MoleculeRecorrectRequest,
    MoleculeRecorrectResponse,
    MoleculeSearchRequest,
    MoleculeSearchResponse,
    MoleculeStatsRequest,
    MoleculeStatsResponse,
    MoleculeUpdateRequest,
    MoleculeUpdateResponse,
)
from ...services.molecule.queries import (
    bulk_update_status,
    create_molecule,
    delete_molecules,
    get_molecule,
    list_molecule_corrections,
    list_molecules_sync,
    molecule_evidence_chain,
    molecule_stats,
    molecules_by_location,
    search_molecules,
    update_molecule,
)
from ...utils.logger import get_logger
from .._path_utils import resolve_library_root

logger = get_logger("mbforge.molecule_router")

router = APIRouter()


def _root(library_root: str | None) -> str:
    """Single library-root resolution point for this router."""
    return str(resolve_library_root(library_root))


@router.post("/list")
async def mol_list(body: MoleculeListRequest) -> MoleculeListResponse:
    return await asyncio.to_thread(list_molecules_sync, _root(body.library_root), body)


@router.get("/by-location", response_model=MoleculeByLocationResponse)
async def mol_by_location(
    doc_id: str,
    page: int = Query(..., ge=1),
    x0: float = Query(...),
    y0: float = Query(...),
    x1: float = Query(...),
    y1: float = Query(...),
    library_root: str | None = Query(default=None),
) -> MoleculeByLocationResponse:
    """Find molecule evidence overlapping a document location."""
    matches = await asyncio.to_thread(
        molecules_by_location, _root(library_root), doc_id, page, (x0, x1, y0, y1)
    )
    return MoleculeByLocationResponse(matches=matches)


@router.post("/search")
async def mol_search(body: MoleculeSearchRequest) -> MoleculeSearchResponse:
    results = await asyncio.to_thread(
        search_molecules,
        _root(body.library_root),
        body.query,
        top_k=body.top_k,
        mode=body.mode,
        similarity_threshold=body.similarity_threshold,
    )
    return MoleculeSearchResponse(results=results)


@router.post("/get")
async def mol_get(body: MoleculeGetRequest) -> MoleculeGetResponse:
    molecule = await asyncio.to_thread(
        get_molecule, _root(body.library_root), body.mol_id
    )
    return MoleculeGetResponse(molecule=molecule)


@router.post("/evidence")
async def mol_evidence(body: MoleculeEvidenceRequest) -> MoleculeEvidenceResponse:
    """Return the full evidence chain for a canonical molecule."""
    molecule, evidence = await asyncio.to_thread(
        molecule_evidence_chain, _root(body.library_root), body.canonical_smiles
    )
    return MoleculeEvidenceResponse(molecule=molecule, evidence=evidence)


@router.post("/create")
async def mol_create(body: MoleculeCreateRequest) -> MoleculeCreateResponse:
    mol_id = await asyncio.to_thread(
        create_molecule,
        _root(body.library_root),
        body.mol_id,
        body.smiles,
        body.esmiles,
        body.name,
        body.source_type,
    )
    return MoleculeCreateResponse(mol_id=mol_id)


@router.put("/bulk-status")
async def mol_bulk_status(
    body: MoleculeBulkStatusRequest,
) -> MoleculeBulkStatusResponse:
    unique_ids = list(dict.fromkeys(body.mol_ids))
    updated, skipped = await asyncio.to_thread(
        bulk_update_status, _root(body.library_root), unique_ids, body.status
    )
    return MoleculeBulkStatusResponse(updated=updated, skipped=skipped)


@router.put("/{mol_id}")
async def mol_update(
    mol_id: str, body: MoleculeUpdateRequest
) -> MoleculeUpdateResponse:
    updates: dict = {}
    for key in [
        "smiles",
        "name",
        "esmiles",
        "activity",
        "activity_type",
        "units",
        "status",
        "notes",
        "labels",
        "properties",
    ]:
        # The frontend sends molecule tags as ``tags``; map it to the DB column ``labels``.
        if key == "labels" and body.tags is not None:
            val = body.tags
        else:
            val = getattr(body, key, None)
        if val is not None:
            updates[key] = val
    await asyncio.to_thread(update_molecule, _root(body.library_root), mol_id, updates)
    return MoleculeUpdateResponse()


@router.get("/{mol_id}/corrections", response_model=MoleculeCorrectionsResponse)
async def mol_corrections(
    mol_id: str, library_root: str | None = Query(default=None)
) -> MoleculeCorrectionsResponse:
    """Return append-only manual corrections for a molecule."""
    corrections = await asyncio.to_thread(
        list_molecule_corrections, _root(library_root), mol_id
    )
    return MoleculeCorrectionsResponse(corrections=corrections)


@router.delete("/{mol_id}")
async def mol_delete(
    mol_id: str, body: MoleculeDeleteRequest
) -> MoleculeDeleteResponse:
    deleted = await asyncio.to_thread(
        delete_molecules, _root(body.library_root), [mol_id]
    )
    return MoleculeDeleteResponse(deleted=deleted)


@router.post("/bulk-delete")
async def mol_bulk_delete(
    body: MoleculeBulkDeleteRequest,
) -> MoleculeDeleteResponse:
    deleted = await asyncio.to_thread(
        delete_molecules, _root(body.library_root), body.mol_ids
    )
    return MoleculeDeleteResponse(deleted=deleted)


@router.post("/stats")
async def mol_stats(body: MoleculeStatsRequest) -> MoleculeStatsResponse:
    stats = await asyncio.to_thread(molecule_stats, _root(body.library_root))
    return MoleculeStatsResponse(
        total=stats["total"],
        by_status=stats["by_status"],
        by_source=stats["by_source"],
    )


@router.post("/recorrect")
async def mol_recorrect(body: MoleculeRecorrectRequest) -> MoleculeRecorrectResponse:
    """Recorrect molecules using context-based validation rules.

    Re-runs the molecule corrector on existing database molecules.
    Use ``dry_run=true`` (default) to preview corrections without updating.
    """
    from ...services.molecule.recorrection import recorrect_molecules

    result = recorrect_molecules(
        library_root=_root(body.library_root),
        doc_id=body.doc_id,
        dry_run=body.dry_run,
    )

    return MoleculeRecorrectResponse(
        total_molecules=result.total_molecules,
        corrected_count=result.corrected_count,
        flagged_count=result.flagged_count,
        corrections=result.corrections,
        errors=result.errors,
    )

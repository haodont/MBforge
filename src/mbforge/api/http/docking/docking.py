"""HTTP routes for molecular docking (the manual input interface).

Upload a prepared receptor, create docking jobs from library ligands + a search
box, poll job status and download poses. All library paths resolve server-side.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from mbforge.api.http._path_utils import resolve_library_root
from mbforge.domain.docking import DockingBox, DockingLigand
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.foundation.layout import sanitize_upload_filename
from mbforge.service.dto.docking import (
    DockingJobListResponse,
    DockingJobRequest,
    DockingJobResponse,
    EngineStatusResponse,
    ReceptorListResponse,
    ReceptorResponse,
)
from mbforge.service.use_cases.docking import engine_gate, jobs, receptors

router = APIRouter()

_MAX_PDB_BYTES = 64 * 1024 * 1024


def _root(library_root: str | None) -> str:
    return str(resolve_library_root(library_root))


@router.get("/engine/status", response_model=EngineStatusResponse)
async def docking_engine_status() -> EngineStatusResponse:
    """Report whether the docking engine (and GPU) can run right now."""
    result = await asyncio.to_thread(engine_gate.evaluate_engine_gate)
    return EngineStatusResponse(
        ready=result.ready, engine=result.engine, reason=result.reason
    )


@router.post("/receptors", response_model=ReceptorResponse)
async def docking_upload_receptor(
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()] = "",
    library_root: Annotated[str | None, Form()] = None,
) -> ReceptorResponse:
    """Upload a receptor PDB, prepare its PDBQT, and register it."""
    filename = sanitize_upload_filename(file.filename or "")
    content = await file.read()
    if not content:
        raise ValidationError("uploaded receptor is empty")
    if len(content) > _MAX_PDB_BYTES:
        raise ValidationError("receptor file is too large")
    receptor = await asyncio.to_thread(
        receptors.register_receptor,
        _root(library_root),
        name=name,
        filename=filename,
        content=content,
    )
    return ReceptorResponse(receptor=receptor)


@router.get("/receptors", response_model=ReceptorListResponse)
async def docking_list_receptors(library_root: str | None = None) -> ReceptorListResponse:
    items = await asyncio.to_thread(receptors.list_receptors, _root(library_root))
    return ReceptorListResponse(receptors=items)


@router.get("/receptors/{receptor_id}", response_model=ReceptorResponse)
async def docking_get_receptor(
    receptor_id: str, library_root: str | None = None
) -> ReceptorResponse:
    receptor = await asyncio.to_thread(
        receptors.get_receptor, _root(library_root), receptor_id
    )
    return ReceptorResponse(receptor=receptor)


@router.get("/receptors/{receptor_id}/file")
async def docking_receptor_file(
    receptor_id: str, library_root: str | None = None
) -> FileResponse:
    """Serve the receptor's source PDB (or prepared PDBQT) for the 3D viewer."""
    receptor = await asyncio.to_thread(
        receptors.get_receptor, _root(library_root), receptor_id
    )
    meta = receptor.get("meta") or {}
    path = Path(str(meta.get("source_path") or receptor.get("pdbqt_path") or ""))
    if not path.is_file():
        raise NotFoundError("receptor file missing", detail=receptor_id)
    return FileResponse(path, media_type="chemical/x-pdb", filename=path.name)


@router.delete("/receptors/{receptor_id}")
async def docking_delete_receptor(
    receptor_id: str, library_root: str | None = None
) -> dict:
    deleted = await asyncio.to_thread(
        receptors.delete_receptor, _root(library_root), receptor_id
    )
    return {"success": True, "deleted": deleted}


@router.post("/jobs", response_model=DockingJobResponse)
async def docking_create_job(body: DockingJobRequest) -> DockingJobResponse:
    root = _root(body.library_root)
    box = DockingBox(
        center=tuple(float(v) for v in body.box.center),  # type: ignore[arg-type]
        size=tuple(float(v) for v in body.box.size),  # type: ignore[arg-type]
    )
    ligands = [
        DockingLigand(
            label=item.label or item.mol_id or f"ligand-{index + 1}",
            smiles=item.smiles,
            mol_id=item.mol_id,
        )
        for index, item in enumerate(body.ligands)
        if item.smiles.strip()
    ]
    if not ligands:
        raise ValidationError("at least one ligand needs a SMILES")
    job = await asyncio.to_thread(
        jobs.enqueue_job,
        root,
        receptor_id=body.receptor_id,
        ligands=ligands,
        box=box,
        params=body.params,
    )
    return DockingJobResponse(job=job)


@router.get("/jobs", response_model=DockingJobListResponse)
async def docking_list_jobs(
    status: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    library_root: str | None = None,
) -> DockingJobListResponse:
    items = await asyncio.to_thread(
        jobs.list_jobs,
        _root(library_root),
        status=status or None,
        limit=limit,
    )
    return DockingJobListResponse(jobs=items)


@router.get("/jobs/{job_id}", response_model=DockingJobResponse)
async def docking_get_job(job_id: str, library_root: str | None = None) -> DockingJobResponse:
    job = await asyncio.to_thread(jobs.get_job, _root(library_root), job_id)
    return DockingJobResponse(job=job)


@router.post("/jobs/{job_id}/cancel", response_model=DockingJobResponse)
async def docking_cancel_job(job_id: str, library_root: str | None = None) -> DockingJobResponse:
    job = await asyncio.to_thread(jobs.cancel_job, _root(library_root), job_id)
    return DockingJobResponse(job=job)


@router.get("/poses/{pose_id}")
async def docking_download_pose(pose_id: str, library_root: str | None = None) -> FileResponse:
    from mbforge.service.ports import get_repositories

    pose = await asyncio.to_thread(
        get_repositories(_root(library_root)).docking.get_pose, pose_id
    )
    if pose is None or not pose.get("pose_path"):
        raise NotFoundError("pose not found", detail=pose_id)
    path = Path(str(pose["pose_path"]))
    if not path.is_file():
        raise NotFoundError("pose file missing", detail=pose_id)
    return FileResponse(path, media_type="chemical/x-sdf", filename=path.name)

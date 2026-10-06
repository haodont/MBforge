"""Docking jobs: enqueue, list/get, cancel, and the execution body."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mbforge.domain.docking import (
    TERMINAL_DOCKING_STATUSES,
    DockingBox,
    DockingJobStatus,
    DockingLigand,
)
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.foundation.ids import short_id
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger
from mbforge.service.ports import get_repositories
from mbforge.service.ports.docking import DockingRequest

logger = get_logger(__name__)


def _repo(library_root: str | Path):  # noqa: ANN202
    return get_repositories(str(library_root)).docking


def _engine():  # noqa: ANN202 — patched in tests
    from mbforge.service.ports import get_runtime

    return get_runtime().docking_engine.get_docking_engine()


def _wake_worker(library_root: str | Path) -> None:
    try:
        from mbforge.service.ports import get_runtime

        get_runtime().docking_worker.ensure_docking_worker(str(library_root))
    except Exception as exc:  # noqa: BLE001 — best-effort wake
        logger.warning("could not wake docking worker: %s", exc)


def enqueue_job(
    library_root: str | Path,
    *,
    receptor_id: str,
    ligands: Sequence[DockingLigand],
    box: DockingBox,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate inputs, persist a ``pending`` job, and wake the worker."""
    if not receptor_id:
        raise ValidationError("receptor_id is required")
    repo = _repo(library_root)
    if repo.get_receptor(receptor_id) is None:
        raise NotFoundError("receptor not found", detail=receptor_id)
    if not ligands:
        raise ValidationError("at least one ligand is required")
    for ligand in ligands:
        if not ligand.smiles.strip():
            raise ValidationError(f"ligand {ligand.label!r} has no SMILES")

    params = dict(params or {})
    # Fill engine defaults from config so a job is self-describing on retry.
    from mbforge.foundation.config import load_global_config

    docking_cfg = load_global_config().docking
    params.setdefault("search_mode", docking_cfg.search_mode)
    params.setdefault("scoring", docking_cfg.scoring)
    params.setdefault("exhaustiveness", docking_cfg.exhaustiveness)
    params.setdefault("num_modes", docking_cfg.num_modes)
    params.setdefault("seed", docking_cfg.seed)
    params.setdefault("timeout_seconds", docking_cfg.timeout_seconds)
    job = {
        "job_id": short_id(),
        "receptor_id": receptor_id,
        "engine": str(params.get("engine", "unidockpro")),
        "params": params,
        "box": box.to_dict(),
        "ligands": [ligand.to_dict() for ligand in ligands],
        "status": DockingJobStatus.PENDING.value,
        "progress": 0.0,
        "message": "",
    }
    repo.insert_job(job)
    _wake_worker(library_root)
    logger.info("Enqueued docking job %s (%d ligands)", job["job_id"], len(ligands))
    return repo.get_job(job["job_id"]) or job


def list_jobs(
    library_root: str | Path, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    return _repo(library_root).list_jobs(status=status, limit=limit)


def get_job(library_root: str | Path, job_id: str) -> dict[str, Any]:
    repo = _repo(library_root)
    job = repo.get_job(job_id)
    if job is None:
        raise NotFoundError("docking job not found", detail=job_id)
    job["poses"] = repo.list_poses(job_id)
    return job


def cancel_job(library_root: str | Path, job_id: str) -> dict[str, Any]:
    repo = _repo(library_root)
    job = repo.get_job(job_id)
    if job is None:
        raise NotFoundError("docking job not found", detail=job_id)
    if job["status"] in {status.value for status in TERMINAL_DOCKING_STATUSES}:
        raise ValidationError(f"job already {job['status']}")
    _signal_cancel(job_id)
    repo.set_job_status(
        job_id,
        DockingJobStatus.CANCELLED.value,
        message="cancelled",
        finished=True,
    )
    return repo.get_job(job_id) or job


def _signal_cancel(job_id: str) -> None:
    try:
        from mbforge.service.pipeline.cancellation import default_registry

        default_registry.cancel(job_id)
    except Exception:  # noqa: BLE001 — cancellation signal is best-effort
        pass


def is_cancelled(job_id: str) -> bool:
    try:
        from mbforge.service.pipeline.cancellation import default_registry

        return default_registry.is_cancelled(job_id)
    except Exception:  # noqa: BLE001
        return False


def _clear_cancel(job_id: str) -> None:
    try:
        from mbforge.service.pipeline.cancellation import default_registry

        default_registry.unregister(job_id)
    except Exception:  # noqa: BLE001
        pass


def run_job(library_root: str | Path, job: dict[str, Any]) -> None:
    """Execute one claimed job and persist its poses (blocking).

    The caller (worker) sets ``running`` first and handles failure; this
    function only performs the engine run and the ``done`` transition.
    """
    repo = _repo(library_root)
    job_id = job["job_id"]
    receptor = repo.get_receptor(job["receptor_id"])
    if receptor is None:
        raise NotFoundError("receptor not found", detail=job["receptor_id"])

    ligands = [
        DockingLigand(
            label=str(item["label"]),
            smiles=str(item["smiles"]),
            mol_id=item.get("mol_id"),
        )
        for item in job["ligands"]
    ]
    box = DockingBox.from_dict(job["box"])

    layout = LibraryLayout(library_root)
    out_dir = layout.docking_job_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    repo.set_job_status(
        job_id, DockingJobStatus.RUNNING.value, progress=0.0, message="docking"
    )
    request = DockingRequest(
        receptor_pdbqt=Path(receptor["pdbqt_path"]),
        ligands=ligands,
        box=box,
        out_dir=out_dir,
        options=dict(job["params"] or {}),
    )
    poses = _engine().dock(request)

    for pose in poses:
        repo.insert_pose(
            {
                "pose_id": short_id(),
                "job_id": job_id,
                "mol_id": pose.mol_id,
                "ligand_label": pose.label,
                "affinity": pose.affinity,
                "rmsd_lb": pose.rmsd_lb,
                "rmsd_ub": pose.rmsd_ub,
                "rank": pose.rank,
                "pose_path": pose.pose_path,
            }
        )
    repo.set_job_status(
        job_id,
        DockingJobStatus.DONE.value,
        progress=1.0,
        message=f"{len(poses)} poses",
        finished=True,
    )
    _clear_cancel(job_id)


__all__ = [
    "cancel_job",
    "enqueue_job",
    "get_job",
    "is_cancelled",
    "list_jobs",
    "run_job",
]

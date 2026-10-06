"""Molecular docking domain types.

Pure value objects for the docking feature: a receptor, a docking box, a ligand
reference, and the job/pose records. Persistence lives in
:mod:`mbforge.db.sqlite.docking_store`; the engine lives in
:mod:`mbforge.foundation.docking`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from mbforge.foundation.errors import ValidationError


class DockingJobStatus(StrEnum):
    """Lifecycle of one docking job."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Statuses past which a job never transitions again.
TERMINAL_DOCKING_STATUSES: frozenset[DockingJobStatus] = frozenset(
    {DockingJobStatus.DONE, DockingJobStatus.FAILED, DockingJobStatus.CANCELLED}
)


@dataclass(frozen=True)
class DockingBox:
    """Search box for docking: center + size in Ångström (receptor frame)."""

    center: tuple[float, float, float]
    size: tuple[float, float, float]

    def __post_init__(self) -> None:
        if len(self.center) != 3 or len(self.size) != 3:
            raise ValidationError("box center and size must each have 3 numbers")
        if any(value <= 0 for value in self.size):
            raise ValidationError("box size must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"center": list(self.center), "size": list(self.size)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DockingBox:
        try:
            center = tuple(float(v) for v in data["center"])
            size = tuple(float(v) for v in data["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("box requires center and size triples") from exc
        return cls(center=center, size=size)  # type: ignore[arg-type]


@dataclass(frozen=True)
class DockingLigand:
    """A ligand to dock: a library molecule (``mol_id``) or a raw SMILES."""

    label: str
    smiles: str
    mol_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "smiles": self.smiles, "mol_id": self.mol_id}


@dataclass(frozen=True)
class Receptor:
    """A prepared receptor (PDB uploaded, PDBQT derived)."""

    receptor_id: str
    name: str
    source_filename: str
    pdbqt_path: str
    file_hash: str = ""
    chain: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "receptor_id": self.receptor_id,
            "name": self.name,
            "source_filename": self.source_filename,
            "pdbqt_path": self.pdbqt_path,
            "file_hash": self.file_hash,
            "chain": self.chain,
            "meta": self.meta,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DockingRequest:
    """Everything one engine run needs; paths point at prepared inputs."""

    receptor_pdbqt: Path
    ligands: Sequence[DockingLigand]
    box: DockingBox
    out_dir: Path
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DockingPose:
    """One ranked docking result: affinity (kcal/mol) and a pose file."""

    label: str
    mol_id: str | None
    affinity: float | None
    rmsd_lb: float | None
    rmsd_ub: float | None
    rank: int
    pose_path: str


__all__ = [
    "TERMINAL_DOCKING_STATUSES",
    "DockingBox",
    "DockingJobStatus",
    "DockingLigand",
    "DockingPose",
    "DockingRequest",
    "Receptor",
]

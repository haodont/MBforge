"""Prepared receptors for docking: register (upload + prep), list, delete."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from mbforge.foundation.docking.prep import prepare_receptor_pdbqt
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.foundation.ids import short_id
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger
from mbforge.service.ports import get_repositories

logger = get_logger(__name__)


def _repo(library_root: str | Path):  # noqa: ANN202
    return get_repositories(str(library_root)).docking


def register_receptor(
    library_root: str | Path,
    *,
    name: str,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    """Store an uploaded PDB, prepare its PDBQT, and register the receptor.

    Blocking (runs the prep tool); callers should offload it to a thread.
    """
    if not content:
        raise ValidationError("receptor file is empty")
    if not filename.lower().endswith(".pdb"):
        raise ValidationError("receptor must be a .pdb file")

    receptor_id = short_id()
    layout = LibraryLayout(library_root)
    receptor_dir = layout.receptor_dir(receptor_id)
    receptor_dir.mkdir(parents=True, exist_ok=True)
    source = layout.receptor_source(receptor_id, filename)
    source.write_bytes(content)

    pdbqt = layout.receptor_pdbqt(receptor_id)
    try:
        prepare_receptor_pdbqt(source, pdbqt)
    except Exception:
        shutil.rmtree(receptor_dir, ignore_errors=True)
        raise

    record = {
        "receptor_id": receptor_id,
        "name": (name or Path(filename).stem).strip(),
        "source_filename": filename,
        "pdbqt_path": str(pdbqt),
        "file_hash": hashlib.sha256(content).hexdigest(),
        "chain": "",
        "meta": {"source_path": str(source)},
    }
    repo = _repo(library_root)
    repo.insert_receptor(record)
    logger.info("Registered receptor %s (%s)", receptor_id, record["name"])
    return repo.get_receptor(receptor_id) or record


def list_receptors(library_root: str | Path) -> list[dict[str, Any]]:
    return _repo(library_root).list_receptors()


def get_receptor(library_root: str | Path, receptor_id: str) -> dict[str, Any]:
    receptor = _repo(library_root).get_receptor(receptor_id)
    if receptor is None:
        raise NotFoundError("receptor not found", detail=receptor_id)
    return receptor


def delete_receptor(library_root: str | Path, receptor_id: str) -> int:
    repo = _repo(library_root)
    if repo.get_receptor(receptor_id) is None:
        raise NotFoundError("receptor not found", detail=receptor_id)
    deleted = repo.delete_receptor(receptor_id)
    shutil.rmtree(LibraryLayout(library_root).receptor_dir(receptor_id), ignore_errors=True)
    return deleted


__all__ = [
    "delete_receptor",
    "get_receptor",
    "list_receptors",
    "register_receptor",
]

"""Receptor / ligand preparation for docking (local, no network).

UniDock-Pro consumes AutoDock **PDBQT** for both the receptor and each ligand,
so preparation is a real conversion, not a rename. Both conversions come from
Meeko (the same library Uni-Dock Tools builds on):

* Ligands start as a SMILES. RDKit builds a 3D conformer; Meeko
  (``MoleculePreparation`` + ``PDBQTWriterLegacy``) writes the PDBQT.
* Receptors start as an uploaded PDB. Meeko's ``mk_prepare_receptor``
  (``--read_pdb``, which avoids a ProDy dependency) writes ``*_rigid.pdbqt``.

Meeko is an installable dependency (the ``docking`` extra). When it is missing
we raise a clear :class:`DockingUnavailableError` rather than emitting a wrong
file.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from pathlib import Path

from mbforge.foundation.docking.errors import (
    DockingError,
    DockingUnavailableError,
)
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.foundation.docking.prep")

_RECEPTOR_PREP_TIMEOUT_S = 300


def _rdkit():  # noqa: ANN202 — lazy import keeps module import cheap
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:  # pragma: no cover — rdkit is a core dependency
        raise DockingUnavailableError("rdkit is required for docking") from exc
    return Chem, AllChem


def _meeko():  # noqa: ANN202
    try:
        from meeko import MoleculePreparation, PDBQTWriterLegacy
    except ImportError as exc:
        raise DockingUnavailableError(
            "meeko is required to prepare docking inputs (uv pip install meeko gemmi)"
        ) from exc
    return MoleculePreparation, PDBQTWriterLegacy


def _embed(smiles: str, *, random_seed: int, minimize: bool):  # noqa: ANN202
    """Return a 3D, hydrogen-added RDKit mol from SMILES."""
    chem, allchem = _rdkit()
    mol = chem.MolFromSmiles(smiles)
    if mol is None:
        raise DockingError(f"invalid SMILES: {smiles!r}")
    mol = chem.AddHs(mol)

    params = allchem.ETKDGv3()
    params.randomSeed = random_seed
    with contextlib.suppress(AttributeError):  # pragma: no cover — older rdkit
        params.numThreads = 0
    if allchem.EmbedMolecule(mol, params) != 0:
        raise DockingError(f"3D embedding failed for SMILES: {smiles!r}")

    if minimize:
        try:
            allchem.MMFFOptimizeMolecule(mol)
        except Exception as exc:  # noqa: BLE001 — optimization is best-effort
            logger.warning("MMFF optimization skipped: %s", exc)
    return mol


def prepare_ligand_pdbqt(
    smiles: str,
    out_path: Path,
    *,
    random_seed: int = 42,
    minimize: bool = True,
) -> Path:
    """SMILES → 3D conformer → AutoDock PDBQT (via Meeko)."""
    molecul_preparation, pdbqt_writer = _meeko()
    mol = _embed(smiles, random_seed=random_seed, minimize=minimize)

    preparations = molecul_preparation().prepare(mol)
    if not preparations:
        raise DockingError(f"meeko could not prepare ligand: {smiles!r}")
    pdbqt, is_ok, error = pdbqt_writer.write_string(preparations[0])
    if not is_ok:
        raise DockingError(f"meeko PDBQT write failed: {error}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(pdbqt, encoding="utf-8")
    return out_path


def prepare_receptor_pdbqt(
    pdb_path: Path,
    out_path: Path,
    *,
    remove_water: bool = True,
    add_hydrogens: bool = True,
    keep_hetero: bool = False,
) -> Path:
    """Convert an uploaded PDB into a rigid PDBQT receptor (via Meeko)."""
    if not pdb_path.is_file():
        raise DockingError(f"receptor PDB not found: {pdb_path}")
    try:
        import meeko  # noqa: F401
    except ImportError as exc:
        raise DockingUnavailableError(
            "receptor preparation needs meeko (uv pip install meeko gemmi)"
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = out_path.parent / f"{out_path.stem}__prep"
    command = _receptor_prep_command(str(pdb_path), str(base))
    logger.info("Preparing receptor: %s", " ".join(command))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_RECEPTOR_PREP_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DockingError("receptor preparation timed out") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:400]
        raise DockingError(f"receptor preparation failed: {detail}")

    # With flexible residues Meeko writes ``<base>_rigid.pdbqt``; a plain
    # receptor is written as ``<base>.pdbqt`` (the static/rigid input).
    produced = sorted(out_path.parent.glob(f"{base.name}*.pdbqt"))
    rigid = next((p for p in produced if p.stem.endswith("_rigid")), None)
    if rigid is None:
        rigid = next((p for p in produced if p.stem == base.name), None)
    if rigid is None and produced:
        rigid = produced[0]
    if rigid is None:
        raise DockingError("receptor preparation produced no rigid PDBQT")
    shutil.move(str(rigid), str(out_path))
    for leftover in out_path.parent.glob(f"{base.name}*"):
        with contextlib.suppress(OSError):
            leftover.unlink()
    return out_path


def _receptor_prep_command(pdb: str, base: str) -> list[str]:
    """Build the ``mk_prepare_receptor`` command (Meeko's receptor prep).

    ``--read_pdb`` reads a PDB without ProDy; ``-p`` writes the ``_rigid`` /
    ``_flex`` PDBQT next to the output basename.
    """
    executable = shutil.which("mk_prepare_receptor.py")
    if executable:
        return [executable, "--read_pdb", pdb, "-o", base, "-p"]
    return [
        sys.executable,
        "-m",
        "meeko.cli.mk_prepare_receptor",
        "--read_pdb",
        pdb,
        "-o",
        base,
        "-p",
    ]


__all__ = ["prepare_ligand_pdbqt", "prepare_receptor_pdbqt"]

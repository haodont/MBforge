"""UniDock-Pro engine adapter (GPU, AutoDock-Vina compatible fork).

UniDock-Pro (``NiBoyang/UniDock-Pro``) is a single binary, ``udp``, that
consumes an AutoDock **PDBQT** receptor and PDBQT ligands. This adapter prepares
each ligand (SMILES → PDBQT via Meeko), writes a ligand-index file, runs one
classical docking job, and parses the ``minimizedAffinity`` / ``minimizedRMSD``
remarks from the produced poses.

Reference: https://github.com/NiBoyang/UniDock-Pro — key contract:
``--search_mode`` is REQUIRED (``fast`` | ``balance`` | ``detail``), ligands are
passed via ``--ligand_index`` (a file of PDBQT paths) or ``--ligand_directory``,
the box is ``--center_{x,y,z}`` + ``--size_{x,y,z}`` (Å), and output goes to
``--dir``. Availability is probed without importing heavy deps so it is safe to
poll from a readiness endpoint. Tests use a fake engine instead.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from mbforge.domain.docking import DockingLigand, DockingPose, DockingRequest
from mbforge.foundation.docking.errors import DockingError, DockingUnavailableError
from mbforge.foundation.docking.prep import prepare_ligand_pdbqt
from mbforge.foundation.inference.device import is_gpu_available
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.foundation.docking.engine")

#: Candidate executable names for UniDock-Pro (env override wins). The built
#: binary is ``udp``; the other names are accepted for convenience.
_ENGINE_BINARIES = ("udp", "unidockpro", "unidock_pro", "unidock")

#: UniDock-Pro requires an explicit search mode.
_SEARCH_MODES = ("fast", "balance", "detail")
_DEFAULT_SEARCH_MODE = "balance"
_DEFAULT_SCORING = "vina"

_AFFINITY_RE = re.compile(r"REMARK\s+minimizedAffinity\s+(-?\d+(?:\.\d+)?)", re.I)
_RMSD_RE = re.compile(r"REMARK\s+minimizedRMSD\s+(-?\d+(?:\.\d+)?)", re.I)
_SDF_AFFINITY_RE = re.compile(r"minimizedAffinity[^\n]*\n\s*(-?\d+(?:\.\d+)?)", re.I)


def _engine_binary() -> str | None:
    override = os.environ.get("MBFORGE_UNIDOCK_BIN")
    if override and Path(override).is_file():
        return override
    for name in _ENGINE_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _safe(label: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label) or "ligand"


class UnidockProEngine:
    """The default GPU docking engine (UniDock-Pro / ``udp``)."""

    name = "unidockpro"

    def availability(self) -> tuple[bool, str]:
        if _engine_binary() is None:
            return False, "UniDock-Pro executable (udp) not found on PATH"
        if not is_gpu_available():
            return False, "no CUDA GPU available (set MBFORGE_FORCE_CPU=0 to enable)"
        return True, ""

    def dock(self, request: DockingRequest) -> list[DockingPose]:
        binary = _engine_binary()
        if binary is None:
            raise DockingUnavailableError(
                "UniDock-Pro executable not found on PATH (build it and put 'udp' "
                "on PATH, or set MBFORGE_UNIDOCK_BIN)"
            )

        options = dict(request.options or {})
        search_mode = str(options.get("search_mode", _DEFAULT_SEARCH_MODE)).lower()
        if search_mode not in _SEARCH_MODES:
            raise DockingError(
                f"invalid search_mode {search_mode!r}; expected one of {_SEARCH_MODES}"
            )

        ligands_dir = request.out_dir / "ligands"
        ligands_dir.mkdir(parents=True, exist_ok=True)
        out_dir = request.out_dir / "poses"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Prepare each ligand to PDBQT and record its label for output mapping.
        index_lines: list[str] = []
        label_by_stem: dict[str, DockingLigand] = {}
        for ligand in request.ligands:
            stem = _safe(ligand.label)
            pdbqt = prepare_ligand_pdbqt(
                ligand.smiles,
                ligands_dir / f"{stem}.pdbqt",
                random_seed=int(options.get("seed", 42)),
                minimize=bool(options.get("minimize", True)),
            )
            index_lines.append(str(pdbqt))
            label_by_stem[stem] = ligand

        index_path = request.out_dir / "ligand_index.txt"
        index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")

        timeout = int(options.get("timeout_seconds", 300))
        self._run(binary, request, index_path, search_mode, out_dir, options, timeout)

        poses = _parse_poses(out_dir, label_by_stem)
        if not poses:
            raise DockingError("UniDock-Pro produced no poses")
        poses.sort(key=lambda pose: (pose.affinity is None, pose.affinity or 0.0))
        return poses

    def _run(
        self,
        binary: str,
        request: DockingRequest,
        index_path: Path,
        search_mode: str,
        out_dir: Path,
        options: dict[str, object],
        timeout: int,
    ) -> None:
        center = request.box.center
        size = request.box.size
        cmd = [
            binary,
            "--receptor", str(request.receptor_pdbqt),
            "--ligand_index", str(index_path),
            "--center_x", str(center[0]),
            "--center_y", str(center[1]),
            "--center_z", str(center[2]),
            "--size_x", str(size[0]),
            "--size_y", str(size[1]),
            "--size_z", str(size[2]),
            "--search_mode", search_mode,
            "--scoring", str(options.get("scoring", _DEFAULT_SCORING)),
            "--exhaustiveness", str(int(options.get("exhaustiveness", 8))),
            "--num_modes", str(int(options.get("num_modes", 9))),
            "--seed", str(int(options.get("seed", 0))),
            "--dir", str(out_dir),
        ]
        logger.info("Running UniDock-Pro: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise DockingError(f"docking timed out after {timeout}s") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:400]
            raise DockingError(f"UniDock-Pro failed (exit {result.returncode}): {detail}")


def _parse_poses(
    out_dir: Path, label_by_stem: dict[str, DockingLigand]
) -> list[DockingPose]:
    """Read poses and their scores from UniDock-Pro's output directory."""
    poses: list[DockingPose] = []
    for path in sorted(out_dir.rglob("*")):
        if path.suffix.lower() not in (".pdbqt", ".sdf"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        ligand = _ligand_for(path, label_by_stem)
        for rank, block in enumerate(_split_models(text)):
            affinity = _affinity(block)
            rmsd = _first_match(_RMSD_RE, block)
            poses.append(
                DockingPose(
                    label=ligand.label if ligand else path.stem,
                    mol_id=ligand.mol_id if ligand else None,
                    affinity=affinity,
                    rmsd_lb=rmsd,
                    rmsd_ub=None,
                    rank=rank,
                    pose_path=str(path),
                )
            )
    return poses


def _ligand_for(path: Path, label_by_stem: dict[str, DockingLigand]) -> DockingLigand | None:
    stem = path.stem
    for suffix in ("_out", "_docked"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return label_by_stem.get(stem)


def _split_models(text: str) -> list[str]:
    """Split a PDBQT/SDF multi-model file; a single model is one block."""
    if "MODEL" not in text.upper():
        return [text]
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("MODEL"):
            if current:
                blocks.append("\n".join(current))
            current = []
        elif line.startswith("ENDMDL"):
            blocks.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [block for block in blocks if block.strip()]


def _affinity(block: str) -> float | None:
    value = _first_match(_AFFINITY_RE, block)
    if value is None:
        value = _first_match(_SDF_AFFINITY_RE, block)
    return value


def _first_match(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


__all__ = ["UnidockProEngine"]

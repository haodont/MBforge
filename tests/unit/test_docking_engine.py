"""UniDock-Pro adapter: command contract + pose parsing (stub `udp`, no GPU)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from mbforge.domain.docking import DockingBox, DockingLigand, DockingRequest
from mbforge.foundation.docking import engine as engine_module
from mbforge.foundation.docking.engine import UnidockProEngine

_STUB_UDP = """#!/bin/sh
dir=""
prev=""
for a in "$@"; do
  if [ "$prev" = "--dir" ]; then dir="$a"; fi
  prev="$a"
done
mkdir -p "$dir"
printf '%s\\n' "$@" > "$dir/args.txt"
printf 'MODEL 1\\nREMARK minimizedAffinity -7.5\\nREMARK minimizedRMSD 0.20\\nATOM\\nENDMDL\\n' > "$dir/L1_out.pdbqt"
printf 'MODEL 1\\nREMARK minimizedAffinity -6.1\\nENDMDL\\n' > "$dir/L2_out.pdbqt"
exit 0
"""


def _stub_ligand_pdbqt(smiles, out_path, **_kwargs):  # noqa: ANN001
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("ATOM\n", encoding="utf-8")
    return out_path


def test_udp_command_and_pose_parsing(tmp_path: Path, monkeypatch) -> None:
    stub = tmp_path / "udp"
    stub.write_text(_STUB_UDP, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("MBFORGE_UNIDOCK_BIN", str(stub))
    monkeypatch.setattr(engine_module, "prepare_ligand_pdbqt", _stub_ligand_pdbqt)

    request = DockingRequest(
        receptor_pdbqt=tmp_path / "rec.pdbqt",
        ligands=[DockingLigand(label="L1", smiles="CCO"), DockingLigand(label="L2", smiles="CCN")],
        box=DockingBox(center=(1.0, 2.0, 3.0), size=(20.0, 20.0, 20.0)),
        out_dir=tmp_path / "job",
        options={"search_mode": "fast", "num_modes": 9, "seed": 7},
    )
    poses = UnidockProEngine().dock(request)

    assert [(p.label, p.affinity) for p in poses] == [("L1", -7.5), ("L2", -6.1)]
    assert poses[0].rmsd_lb == 0.2

    args = (tmp_path / "job" / "poses" / "args.txt").read_text(encoding="utf-8").splitlines()
    assert "--search_mode" in args and args[args.index("--search_mode") + 1] == "fast"
    assert "--receptor" in args
    assert "--ligand_index" in args
    assert args[args.index("--center_x") + 1] == "1.0"
    assert args[args.index("--size_z") + 1] == "20.0"
    assert args[args.index("--scoring") + 1] == "vina"
    assert args[args.index("--seed") + 1] == "7"


def test_invalid_search_mode_is_rejected(tmp_path: Path, monkeypatch) -> None:
    stub = tmp_path / "udp"
    stub.write_text(_STUB_UDP, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MBFORGE_UNIDOCK_BIN", str(stub))

    request = DockingRequest(
        receptor_pdbqt=tmp_path / "rec.pdbqt",
        ligands=[DockingLigand(label="L1", smiles="CCO")],
        box=DockingBox(center=(0.0, 0.0, 0.0), size=(10.0, 10.0, 10.0)),
        out_dir=tmp_path / "job",
        options={"search_mode": "turbo"},
    )
    with pytest.raises(Exception, match="search_mode"):
        UnidockProEngine().dock(request)


def test_availability_reports_missing_binary(monkeypatch) -> None:
    monkeypatch.delenv("MBFORGE_UNIDOCK_BIN", raising=False)
    monkeypatch.setattr(engine_module.shutil, "which", lambda _name: None)
    available, reason = UnidockProEngine().availability()
    assert available is False
    assert "udp" in reason


@pytest.mark.parametrize("name", ["unidockpro", "unidock_pro", "unidock"])
def test_binary_candidates_are_searched(name: str, monkeypatch) -> None:
    monkeypatch.delenv("MBFORGE_UNIDOCK_BIN", raising=False)
    calls: list[str] = []

    def _which(candidate: str) -> str | None:
        calls.append(candidate)
        return f"/usr/bin/{candidate}" if candidate == name else None

    monkeypatch.setattr(engine_module.shutil, "which", _which)
    binary = engine_module._engine_binary()
    if name == "udp":
        assert calls[0] == "udp"
    assert binary == f"/usr/bin/{name}"
    assert os.path.basename(binary) == name


def test_prepare_ligand_pdbqt_writes_a_real_pdbqt(tmp_path: Path) -> None:
    """The real prep chain (RDKit 3D + Meeko) produces a dockable PDBQT."""
    pytest.importorskip("meeko")
    from mbforge.foundation.docking.prep import prepare_ligand_pdbqt

    out = prepare_ligand_pdbqt("CCO", tmp_path / "ethanol.pdbqt")
    text = out.read_text(encoding="utf-8")
    assert "ROOT" in text
    assert "TORSDOF" in text
    assert "BRANCH" in text  # ethanol has one rotatable bond (C-O)

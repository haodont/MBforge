"""Docking HTTP + use-case contract (fake engine; no GPU / network)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.domain.docking import DockingPose
from mbforge.server.app import create_app


class FakeEngine:
    """Deterministic engine stand-in for tests."""

    name = "fake"

    def __init__(self, available: bool = True, reason: str = "") -> None:
        self._available = available
        self._reason = reason

    def availability(self) -> tuple[bool, str]:
        return self._available, self._reason

    def dock(self, request) -> list[DockingPose]:
        poses: list[DockingPose] = []
        for index, ligand in enumerate(request.ligands):
            pose_path = request.out_dir / "poses" / f"{ligand.label}_{index}.sdf"
            pose_path.parent.mkdir(parents=True, exist_ok=True)
            pose_path.write_text("", encoding="utf-8")
            poses.append(
                DockingPose(
                    label=ligand.label,
                    mol_id=ligand.mol_id,
                    affinity=-7.5 - index,
                    rmsd_lb=0.0,
                    rmsd_ub=0.0,
                    rank=0,
                    pose_path=str(pose_path),
                )
            )
        return poses


def _noop_prep(src, out, **kwargs):  # noqa: ANN001
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("PDBQT", encoding="utf-8")
    return out


def test_docking_engine_status_reports_gate(monkeypatch) -> None:
    from mbforge.service.use_cases.docking import engine_gate

    monkeypatch.setattr(engine_gate, "_engine", lambda: FakeEngine(False, "no gpu"))
    response = TestClient(create_app()).get("/api/v1/docking/engine/status")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "ready": False,
        "engine": "fake",
        "reason": "no gpu",
    }


def test_receptor_upload_prepares_and_registers(
    app_client: TestClient, tmp_library: Path, monkeypatch
) -> None:
    from mbforge.service.use_cases.docking import receptors as receptors_uc

    monkeypatch.setattr(receptors_uc, "prepare_receptor_pdbqt", _noop_prep)

    response = app_client.post(
        "/api/v1/docking/receptors",
        files={"file": ("receptor.pdb", b"ATOM      1  N   ALA A   1\n", "chemical/x-pdb")},
        data={"name": "Test Receptor"},
    )

    assert response.status_code == 200
    receptor = response.json()["receptor"]
    assert receptor["name"] == "Test Receptor"
    pdbqt = (
        tmp_library / "docking" / "receptors" / receptor["receptor_id"] / "receptor.pdbqt"
    )
    assert pdbqt.is_file()

    listed = app_client.get("/api/v1/docking/receptors").json()["receptors"]
    assert [item["receptor_id"] for item in listed] == [receptor["receptor_id"]]


def test_create_job_then_run_writes_ranked_poses(
    app_client: TestClient, tmp_library: Path, monkeypatch
) -> None:
    from mbforge.service.use_cases.docking import jobs as jobs_uc
    from mbforge.service.use_cases.docking import receptors as receptors_uc

    monkeypatch.setattr(receptors_uc, "prepare_receptor_pdbqt", _noop_prep)
    monkeypatch.setattr(jobs_uc, "_wake_worker", lambda _root: None)
    monkeypatch.setattr(jobs_uc, "_engine", lambda: FakeEngine())

    receptor = app_client.post(
        "/api/v1/docking/receptors",
        files={"file": ("r.pdb", b"ATOM\n", "chemical/x-pdb")},
        data={"name": "R"},
    ).json()["receptor"]

    created = app_client.post(
        "/api/v1/docking/jobs",
        json={
            "receptor_id": receptor["receptor_id"],
            "ligands": [{"label": "L1", "smiles": "CCO"}],
            "box": {"center": [0, 0, 0], "size": [20, 20, 20]},
        },
    ).json()["job"]
    assert created["status"] == "pending"

    jobs_uc.run_job(str(tmp_library), created)

    job = app_client.get(f"/api/v1/docking/jobs/{created['job_id']}").json()["job"]
    assert job["status"] == "done"
    assert len(job["poses"]) == 1
    assert job["poses"][0]["ligand_label"] == "L1"
    assert job["poses"][0]["affinity"] == -7.5

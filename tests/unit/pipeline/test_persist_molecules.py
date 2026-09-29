"""Tests for the persist_molecule_candidates structure-role gate."""

from __future__ import annotations

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource
from mbforge.service.pipeline.persist.molecules import persist_molecule_candidates


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def _candidate(smiles: str, *, status: str = "pending") -> Molecule:
    return Molecule(
        canonical_smiles=smiles,
        esmiles=smiles,
        name="",
        detections=[
            DetectionSource(
                source="image",
                page=1,
                bbox=(0, 0, 1, 1),
                image_path="crop.png",
                confidence=0.9,
            )
        ],
        status=status,  # type: ignore[arg-type]
    )


def test_direct_molecule_persistence_skips_non_complete_role(
    database, tmp_path
) -> None:
    """Direct callers cannot bypass the role gate and add Markush to molecules."""
    scaffold = _candidate("*c1ccc(*)cc1")
    scaffold.properties["structure_role"] = "scaffold"
    persist_molecule_candidates(str(tmp_path), "doc-1", [scaffold])
    assert (
        database.execute("SELECT COUNT(*) AS count FROM molecules", db="mol")[0][
            "count"
        ]
        == 0
    )


def test_direct_molecule_persistence_classifies_unclassified_markush(
    database, tmp_path
) -> None:
    """An unclassified Markush candidate cannot bypass the main-library gate."""
    scaffold = _candidate("*c1ccc(*)cc1" + "C" * 13)
    persist_molecule_candidates(str(tmp_path), "doc-1", [scaffold])
    assert (
        database.execute("SELECT COUNT(*) AS count FROM molecules", db="mol")[0][
            "count"
        ]
        == 0
    )
    assert scaffold.properties["structure_role"] == "scaffold"


def test_persist_stores_source_evidence_link(database, tmp_path) -> None:
    """A persisted molecule row keeps its canonical source_evidence id."""
    candidate = _candidate("CCO")
    candidate.detections[0] = DetectionSource(
        source="image",
        page=1,
        bbox=(0, 0, 1, 1),
        image_path="crop.png",
        confidence=0.9,
        evidence_id="ev-1",
    )
    persist_molecule_candidates(str(tmp_path), "doc-1", [candidate])
    with database.mol_conn() as conn:
        row = conn.execute(
            "SELECT evidence_id FROM evidence WHERE canonical_smiles = 'CCO'"
        ).fetchone()
    assert row is not None
    assert row["evidence_id"] == "ev-1"

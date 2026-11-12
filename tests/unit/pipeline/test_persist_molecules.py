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


def _molecule_count(database) -> int:
    return database.execute("SELECT COUNT(*) AS count FROM molecules")[0]["count"]


def test_direct_molecule_persistence_cannot_bypass_the_role_gate(
    database, tmp_path
) -> None:
    """Only complete structures reach the main library, even called directly."""
    scaffold = _candidate("*c1ccc(*)cc1")
    scaffold.properties["structure_role"] = "scaffold"
    persist_molecule_candidates(str(tmp_path), "doc-1", [scaffold])
    assert _molecule_count(database) == 0

    # An unclassified Markush candidate is classified here rather than stored.
    unclassified = _candidate("*c1ccc(*)cc1" + "C" * 13)
    persist_molecule_candidates(str(tmp_path), "doc-1", [unclassified])
    assert _molecule_count(database) == 0
    assert unclassified.properties["structure_role"] == "scaffold"


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
    with database.connection() as conn:
        row = conn.execute(
            "SELECT evidence_id, context_text FROM molecule_detections "
            "WHERE mol_id = 'CCO'"
        ).fetchone()
    assert row is not None
    assert row["evidence_id"] == "ev-1"


def test_complete_structures_reach_the_library_without_an_activity(
    database, tmp_path
) -> None:
    """A recognized structure is stored even when no reading cites it yet.

    Regression: the Extract stage never called this function. Concrete
    structures were written to disk as crops and to ``source_evidence``, but
    never to ``molecules``, so a 113-page patent that recognized 290 structures
    reported zero molecules. Only the Patent stage's re-persist (which requires a
    resolvable activity owner) could create rows, which is why documents without
    bound readings had none at all.
    """
    plain = _candidate("CCO")
    plain.properties["structure_role"] = "complete"
    markush = _candidate("*c1ccc(*)cc1")
    markush.properties["structure_role"] = "scaffold"

    persist_molecule_candidates(str(tmp_path), "doc-1", [plain, markush])

    assert _molecule_count(database) == 1
    with database.connection() as conn:
        row = conn.execute("SELECT mol_id FROM molecules").fetchone()
    assert row["mol_id"] == "CCO"

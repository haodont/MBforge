"""Tests for transactional Markush persistence."""

from __future__ import annotations

import pytest

from mbforge.adapters.persistence.sqlite.database import DatabaseManager
from mbforge.application.pipeline.persist.markush import (
    delete_markush_for_doc,
    persist_markush_fragments,
    persist_markush_scaffolds,
)
from mbforge.application.pipeline.persist.molecules import persist_molecule_candidates
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource


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


def test_persist_scaffold_writes_row(database) -> None:
    scaffold = _candidate("*c1ccc(*)cc1")
    scaffold.properties.update(structure_role="scaffold", formula_label="Formula I")
    with database.mol_conn() as conn:
        persist_markush_scaffolds("doc-1", [scaffold], conn=conn)
        row = conn.execute(
            "SELECT doc_id, smiles, formula_label FROM markush_scaffolds"
        ).fetchone()
    assert tuple(row) == ("doc-1", "*c1ccc(*)cc1", "Formula I")


def test_persist_fragment_writes_unmounted_row(database) -> None:
    fragment = _candidate("*c1cscn1")
    fragment.properties.update(structure_role="fragment", label="A1")
    with database.mol_conn() as conn:
        persist_markush_fragments("doc-1", [fragment], conn=conn)
        row = conn.execute(
            "SELECT doc_id, smiles, label, scaffold_id FROM markush_fragments"
        ).fetchone()
    assert tuple(row) == ("doc-1", "*c1cscn1", "A1", None)


def test_persist_skips_mismatched_role_and_rejected(database) -> None:
    wrong_role = _candidate("*c1ccc(*)cc1")
    wrong_role.properties["structure_role"] = "complete"
    rejected = _candidate("*c1cscn1", status="rejected")
    rejected.properties["structure_role"] = "fragment"
    with database.mol_conn() as conn:
        persist_markush_scaffolds("doc-1", [wrong_role], conn=conn)
        persist_markush_fragments("doc-1", [rejected], conn=conn)
        scaffold_count = conn.execute(
            "SELECT COUNT(*) FROM markush_scaffolds"
        ).fetchone()[0]
        fragment_count = conn.execute(
            "SELECT COUNT(*) FROM markush_fragments"
        ).fetchone()[0]
    assert scaffold_count == fragment_count == 0


def test_persist_skips_candidate_without_detection(database) -> None:
    fragment = Molecule(canonical_smiles="*C", esmiles="*C", name="")
    fragment.properties["structure_role"] = "fragment"
    with database.mol_conn() as conn:
        persist_markush_fragments("doc-1", [fragment], conn=conn)
        count = conn.execute("SELECT COUNT(*) FROM markush_fragments").fetchone()[0]
    assert count == 0


def test_reingest_replaces_existing_markush_rows(database) -> None:
    """Cover-overwrite deletes stale rows before persisting a document again."""
    old = _candidate("*c1ccc(*)cc1")
    old.properties["structure_role"] = "scaffold"
    new = _candidate("*c1cc(*)ccc1")
    new.properties["structure_role"] = "scaffold"
    with database.mol_conn() as conn:
        persist_markush_scaffolds("doc-1", [old], conn=conn)
        delete_markush_for_doc("doc-1", conn=conn)
        persist_markush_scaffolds("doc-1", [new], conn=conn)
        rows = conn.execute(
            "SELECT smiles FROM markush_scaffolds WHERE doc_id = ?", ("doc-1",)
        ).fetchall()
    assert [row["smiles"] for row in rows] == ["*c1cc(*)ccc1"]


def test_direct_molecule_persistence_skips_non_complete_role(
    database, tmp_path
) -> None:
    """Direct callers cannot bypass PersistStage and add Markush to molecules."""
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


@pytest.mark.parametrize(
    "persist", [persist_markush_scaffolds, persist_markush_fragments]
)
def test_persist_requires_connection(persist) -> None:
    with pytest.raises(ValueError, match="active connection"):
        persist("doc-1", [], conn=None)

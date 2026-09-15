"""Unit tests for the Markush review state machine and transitions."""

from __future__ import annotations

import pytest

from mbforge.core.molecule import Molecule
from mbforge.core.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
)
from mbforge.core.types import DetectionSource
from mbforge.services.markush.review import apply_decision
from mbforge.storage.markush_candidates import persist_review_candidates
from mbforge.storage.markush_transitions import (
    get_candidate_detail,
    list_candidates,
    update_candidate,
)
from mbforge.storage.sqlite.database import DatabaseManager


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def _seed_one(database, *, smiles: str = "*c1ccccc1", label: str = "R1") -> str:
    """Insert one pending review candidate and return its id."""
    molecule = Molecule(
        canonical_smiles=smiles,
        esmiles=smiles,
        name="",
        detections=[
            DetectionSource(
                source="image",
                page=1,
                bbox=(10.0, 20.0, 110.0, 220.0),
                image_path="crop.png",
                confidence=0.9,
            )
        ],
    )
    molecule.properties["structure_role"] = "review_required"
    molecule.properties["raw_coref_label"] = label
    molecule.properties["normalized_label"] = label
    molecule.properties["label_kind"] = "r_group"
    with database.mol_conn() as conn:
        persist_review_candidates("doc-1", [molecule], conn=conn, recognition_version=1)
        row = conn.execute(
            "SELECT candidate_id FROM markush_review_candidates LIMIT 1"
        ).fetchone()
    return row["candidate_id"]


def test_list_filters_pending_only(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="reject",
            reason="test reject",
        )
        pending, total_pending = list_candidates(conn, review_status="pending")
        rejected, total_rejected = list_candidates(conn, review_status="rejected")
    assert pending == []
    assert total_pending == 0
    assert len(rejected) == 1
    assert rejected[0].review_status == "rejected"
    assert total_rejected == 1


def test_get_detail_includes_evidence_and_decisions(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        detail = get_candidate_detail(conn, candidate_id)
    assert detail.candidate_id == candidate_id
    assert len(detail.evidence) == 1
    assert detail.normalized_label == "R1"
    assert len(detail.decisions) >= 1
    assert detail.decisions[0].action == "candidate_created"


def test_confirm_complete_writes_molecule(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        payload = apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_complete",
            reason="looks like a real molecule",
        )
    assert payload["new_state"] == "confirmed"
    assert payload["molecule_id"]
    with database.mol_conn() as conn:
        mol_row = conn.execute(
            "SELECT mol_id, source_doc, properties FROM molecules WHERE mol_id = ?",
            (payload["molecule_id"],),
        ).fetchone()
    assert mol_row is not None
    assert mol_row["source_doc"] == "doc-1"


def test_confirm_scaffold_writes_markush_scaffold(database) -> None:
    candidate_id = _seed_one(database, label="Formula I")
    with database.mol_conn() as conn:
        payload = apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_scaffold",
        )
    assert payload["scaffold_id"]
    with database.mol_conn() as conn:
        scaffold = conn.execute(
            "SELECT formula_label, status FROM markush_scaffolds WHERE scaffold_id = ?",
            (payload["scaffold_id"],),
        ).fetchone()
    assert scaffold["formula_label"] == "Formula I"
    assert scaffold["status"] == "confirmed"


def test_confirm_fragment_writes_markush_fragment(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        payload = apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_fragment",
        )
    assert payload["fragment_id"]
    with database.mol_conn() as conn:
        fragment = conn.execute(
            "SELECT label, status FROM markush_fragments WHERE fragment_id = ?",
            (payload["fragment_id"],),
        ).fetchone()
    assert fragment["label"] == "R1"
    assert fragment["status"] == "confirmed"


def test_candidate_detail_exposes_fragment_id_and_blocks_enumeration(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        payload = apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_fragment",
        )
        detail = get_candidate_detail(conn, candidate_id)

    assert detail.fragment_id == payload["fragment_id"]
    assert detail.scaffold_id is None
    assert detail.enumeration_eligible is False
    assert detail.enumeration_block_reasons == ["candidate is not a confirmed scaffold"]


def test_candidate_detail_requires_confirmed_scaffold_relationships(database) -> None:
    candidate_id = _seed_one(database, label="Formula I")
    with database.mol_conn() as conn:
        payload = apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_scaffold",
        )
        detail = get_candidate_detail(conn, candidate_id)

    assert detail.scaffold_id == payload["scaffold_id"]
    assert detail.fragment_id is None
    assert detail.enumeration_eligible is False
    assert detail.enumeration_block_reasons == ["no confirmed attachment site"]


def test_candidate_detail_allows_confirmed_scaffold_relationship(database) -> None:
    candidate_id = _seed_one(database, label="Formula I")
    with database.mol_conn() as conn:
        payload = apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_scaffold",
        )
        scaffold_id = str(payload["scaffold_id"])
        conn.execute(
            """
            INSERT INTO markush_sites
                (site_id, scaffold_id, site_label, atom_map_num, status)
            VALUES ('site-1', ?, 'R1', 1, 'confirmed')
            """,
            (scaffold_id,),
        )
        conn.execute(
            """
            INSERT INTO markush_fragments
                (fragment_id, doc_id, label, smiles, status)
            VALUES ('fragment-1', 'doc-1', 'R1', 'F', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_options
                (option_id, site_id, fragment_id, status)
            VALUES ('option-1', 'site-1', 'fragment-1', 'confirmed')
            """
        )
        detail = get_candidate_detail(conn, candidate_id)

    assert detail.enumeration_eligible is True
    assert detail.enumeration_block_reasons == []


def test_decision_increments_version(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        first = apply_decision(
            conn, candidate_id=candidate_id, expected_version=1, action="reject"
        )
    assert first["new_version"] == 2
    # Reopen
    with database.mol_conn() as conn:
        second = apply_decision(
            conn, candidate_id=candidate_id, expected_version=2, action="reopen"
        )
    assert second["new_state"] == "pending"
    assert second["new_version"] == 3


def test_decision_with_stale_version_raises_conflict(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        apply_decision(
            conn, candidate_id=candidate_id, expected_version=1, action="reject"
        )
    with database.mol_conn() as conn, pytest.raises(ReviewConflictError):
        apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="reopen",
        )


def test_reopen_from_pending_is_rejected(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn, pytest.raises(ReviewTransitionError):
        apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="reopen",
        )


def test_confirm_complete_with_empty_smiles_is_rejected(database) -> None:
    candidate_id = _seed_one(database, smiles="")
    with database.mol_conn() as conn, pytest.raises(ReviewTransitionError):
        apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_complete",
        )


def test_update_changes_smiles_and_label(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        updated = update_candidate(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            smiles="*c1ccncc1",
            normalized_label="R2",
            note="fixed",
        )
    assert updated.smiles == "*c1ccncc1"
    assert updated.normalized_label == "R2"
    assert updated.review_version == 2
    with database.mol_conn() as conn:
        decisions = conn.execute(
            "SELECT action FROM markush_decisions WHERE entity_id = ? ORDER BY created_at",
            (candidate_id,),
        ).fetchall()
    assert any(d["action"] == "update" for d in decisions)


def test_update_after_confirm_is_rejected(database) -> None:
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        apply_decision(
            conn, candidate_id=candidate_id, expected_version=1, action="reject"
        )
    with database.mol_conn() as conn, pytest.raises(ReviewTransitionError):
        update_candidate(
            conn,
            candidate_id=candidate_id,
            expected_version=2,
            smiles="*c1ccc(*)cc1",
        )


def test_unknown_candidate_raises_not_found(database) -> None:
    with database.mol_conn() as conn, pytest.raises(ReviewNotFoundError):
        apply_decision(
            conn, candidate_id="does-not-exist", expected_version=1, action="reject"
        )

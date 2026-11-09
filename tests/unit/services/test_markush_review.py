"""Unit tests for the Markush review state machine and transitions.

Covers ``services.use_cases.markush.review.apply_decision`` and the
``db.markush_transitions`` read/update contracts (``list_candidates``,
``get_candidate_detail``, ``update_candidate``).
"""

from __future__ import annotations

import pytest

from mbforge.db.markush_candidates import persist_review_candidates
from mbforge.db.markush_transitions import (
    get_candidate_detail,
    list_candidates,
    update_candidate,
)
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.molecule import Molecule
from mbforge.domain.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
)
from mbforge.domain.types import DetectionSource
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.markush.review import apply_decision


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


@pytest.fixture
def repo(tmp_path):
    return get_repositories(str(tmp_path)).review


def _seed_one(
    database, *, smiles: str = "*c1ccccc1", label: str = "R1", page: int = 1
) -> str:
    """Insert one pending review candidate and return its id.

    ``page`` disambiguates the candidate source key when a test seeds several
    candidates into the same database.
    """
    molecule = Molecule(
        canonical_smiles=smiles,
        esmiles=smiles,
        name="",
        detections=[
            DetectionSource(
                source="image",
                page=page,
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
        # Several tests seed more than one candidate against the same DB, so
        # take the row that was just written, not an arbitrary pending one.
        row = conn.execute(
            "SELECT candidate_id FROM markush_review_candidates "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    return row["candidate_id"]


def test_listing_and_detail_reflect_decisions(database, repo) -> None:
    """A fresh candidate shows evidence and its creation decision; after a
    reject nothing is pending and the queue reports it under ``rejected``."""
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        detail = get_candidate_detail(conn, candidate_id)
    assert detail.candidate_id == candidate_id
    assert len(detail.evidence) == 1
    assert detail.normalized_label == "R1"
    assert len(detail.decisions) >= 1
    assert detail.decisions[0].action == "candidate_created"

    apply_decision(
        repo,
        candidate_id=candidate_id,
        expected_version=1,
        action="reject",
        reason="test reject",
    )
    with database.mol_conn() as conn:
        pending, total_pending = list_candidates(conn, review_status="pending")
        rejected, total_rejected = list_candidates(conn, review_status="rejected")
    assert pending == []
    assert total_pending == 0
    assert len(rejected) == 1
    assert rejected[0].review_status == "rejected"
    assert total_rejected == 1


def test_confirm_actions_mint_the_matching_artifact(database, repo) -> None:
    """confirm_complete mints a molecule, confirm_scaffold a scaffold and
    confirm_fragment a fragment — each keyed to its own candidate."""
    complete_id = _seed_one(database)
    complete = apply_decision(
        repo,
        candidate_id=complete_id,
        expected_version=1,
        action="confirm_complete",
        reason="looks like a real molecule",
    )
    assert complete["new_state"] == "confirmed"
    assert complete["molecule_id"]
    with database.mol_conn() as conn:
        mol_row = conn.execute(
            "SELECT mol_id, source_doc, properties FROM molecules WHERE mol_id = ?",
            (complete["molecule_id"],),
        ).fetchone()
    assert mol_row is not None
    assert mol_row["source_doc"] == "doc-1"

    scaffold_candidate = _seed_one(database, label="Formula I")
    scaffold_decision = apply_decision(
        repo,
        candidate_id=scaffold_candidate,
        expected_version=1,
        action="confirm_scaffold",
    )
    assert scaffold_decision["scaffold_id"]
    with database.mol_conn() as conn:
        scaffold = conn.execute(
            "SELECT formula_label, status FROM markush_scaffolds WHERE scaffold_id = ?",
            (scaffold_decision["scaffold_id"],),
        ).fetchone()
    assert scaffold["formula_label"] == "Formula I"
    assert scaffold["status"] == "confirmed"

    fragment_candidate = _seed_one(database, page=2)
    fragment_decision = apply_decision(
        repo,
        candidate_id=fragment_candidate,
        expected_version=1,
        action="confirm_fragment",
    )
    assert fragment_decision["fragment_id"]
    with database.mol_conn() as conn:
        fragment = conn.execute(
            "SELECT label, status FROM markush_fragments WHERE fragment_id = ?",
            (fragment_decision["fragment_id"],),
        ).fetchone()
    assert fragment["label"] == "R1"
    assert fragment["status"] == "confirmed"


def test_decision_versioning_rejects_stale_and_invalid_transitions(
    database, repo
) -> None:
    """Every decision bumps the version; a stale version conflicts and a
    reopen from ``pending`` is an invalid transition."""
    candidate_id = _seed_one(database)
    first = apply_decision(
        repo, candidate_id=candidate_id, expected_version=1, action="reject"
    )
    assert first["new_version"] == 2
    second = apply_decision(
        repo, candidate_id=candidate_id, expected_version=2, action="reopen"
    )
    assert second["new_state"] == "pending"
    assert second["new_version"] == 3

    with pytest.raises(ReviewConflictError):
        apply_decision(
            repo,
            candidate_id=candidate_id,
            expected_version=1,
            action="reopen",
        )
    with pytest.raises(ReviewTransitionError):
        apply_decision(
            repo,
            candidate_id=candidate_id,
            expected_version=3,
            action="reopen",
        )


def test_invalid_decisions_are_rejected(database, repo) -> None:
    """An empty-SMILES candidate cannot be confirmed complete, and an unknown
    candidate id is a not-found error."""
    candidate_id = _seed_one(database, smiles="")
    with pytest.raises(ReviewTransitionError):
        apply_decision(
            repo,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_complete",
        )

    with pytest.raises(ReviewNotFoundError):
        apply_decision(
            repo, candidate_id="does-not-exist", expected_version=1, action="reject"
        )


def test_update_changes_smiles_and_label_but_not_after_resolution(
    database, repo
) -> None:
    """update_candidate edits a pending candidate (audited) and is refused
    once the candidate is resolved."""
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
            "SELECT action FROM markush_decisions WHERE entity_id = ? "
            "ORDER BY created_at",
            (candidate_id,),
        ).fetchall()
    assert any(d["action"] == "update" for d in decisions)

    apply_decision(repo, candidate_id=candidate_id, expected_version=2, action="reject")
    with database.mol_conn() as conn, pytest.raises(ReviewTransitionError):
        update_candidate(
            conn,
            candidate_id=candidate_id,
            expected_version=3,
            smiles="*c1ccc(*)cc1",
        )

"""Tests for the unified review queue.

Covers ``service.use_cases.review_queue.decide`` (native vs Markush entity
lifecycles, ambiguous coreference, structure corrections) and the
``repositories.review`` contract (queue listing/stats, re-import stability,
``clear_all``).
"""

from __future__ import annotations

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.review_queue import decide


def test_unified_queue_maps_kinds_and_reimport_preserves_human_decision(
    tmp_path,
) -> None:
    """The queue projects native and Markush rows into one listing, and a
    re-import of a resolved item refreshes its fields without losing the
    reviewer's decision."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.mol_conn() as conn:
        repo.insert_review_item(
            item_id="low-1",
            kind="low_conf_molecule",
            doc_id="doc-native",
            page=2,
            bbox=(1, 2, 3, 4),
            smiles="CCO",
            confidence=0.4,
            reasons=["below_threshold"],
            payload={"mol_id": "m1"},
        )
        conn.execute(
            """
            INSERT INTO markush_review_candidates
                (candidate_id, source_key, doc_id, predicted_role, smiles, page,
                 reasons, properties)
            VALUES ('mark-1', 'source-1', 'doc-markush', 'review_required',
                    '*CCO', 0, '["markush_context"]', '{"x": 1}')
            """
        )
        items, total = repo.list_queue(page=1, page_size=10)
        assert total == 2
        assert {item["kind"] for item in items} == {"low_conf_molecule", "markush_link"}
        assert next(item for item in items if item["id"] == "mark-1")["page"] == 1
        assert repo.stats()["pending"] == 2

        decide(repo, kind="low_conf_molecule", item_id="low-1", action="reject")

        repo.insert_review_item(
            item_id="low-1",
            kind="low_conf_molecule",
            doc_id="doc-native",
            smiles="CCN",
            confidence=0.3,
        )

        row = conn.execute(
            "SELECT status, smiles, confidence FROM review_items WHERE item_id = ?",
            ("low-1",),
        ).fetchone()
        assert tuple(row) == ("rejected", "CCN", 0.3)


def test_decide_routes_native_and_markush_entities_to_their_lifecycles(
    tmp_path,
) -> None:
    """Native review items flip their own status and audit row; Markush link
    decisions go through the candidate state machine."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.mol_conn() as conn:
        repo.insert_review_item(
            item_id="activity-1",
            kind="smiles_correction",
            doc_id="doc-1",
            payload={"activity_id": "a1"},
        )
        result = decide(
            repo,
            kind="smiles_correction",
            item_id="activity-1",
            action="reject",
            reason="not enough context",
        )
        assert result["status"] == "rejected"
        row = conn.execute(
            "SELECT status FROM review_items WHERE item_id = 'activity-1'"
        ).fetchone()
        assert row[0] == "rejected"
        audit = conn.execute(
            "SELECT entity_type, action, reason FROM markush_decisions "
            "WHERE entity_id = 'activity-1'"
        ).fetchone()
        assert tuple(audit) == ("review_item", "reject", "not enough context")

        conn.execute(
            """
            INSERT INTO markush_review_candidates
                (candidate_id, source_key, doc_id, predicted_role, smiles)
            VALUES ('mark-1', 'source-1', 'doc-1', 'review_required', '*CCO')
            """
        )

        rejected = decide(
            repo,
            kind="markush_link",
            item_id="mark-1",
            action="reject",
        )
        reopened = decide(
            repo,
            kind="markush_link",
            item_id="mark-1",
            action="reopen",
        )

    assert rejected["new_state"] == "rejected"
    assert reopened["new_state"] == "pending"


def test_ambiguous_coref_confirm_adopts_choice_and_reject_only_resolves(
    tmp_path,
) -> None:
    """confirm adopts the reviewer-chosen identifier (falling back to the
    primary label); reject flips the item and keeps the molecule's name."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.mol_conn() as conn:
        for mol_id in ("mol-1", "mol-2", "mol-3"):
            conn.execute(
                "INSERT INTO molecules (mol_id, smiles, name) VALUES (?, 'CCO', '')",
                (mol_id,),
            )

        repo.insert_review_item(
            item_id="coref-1",
            kind="ambiguous_coref",
            doc_id="doc-1",
            smiles="CCO",
            payload={
                "mol_id": "mol-1",
                "ocr_labels": ["3", "21"],
                "coref_primary": "21",
            },
        )
        result = decide(
            repo,
            kind="ambiguous_coref",
            item_id="coref-1",
            action="confirm",
            choice="21",
        )
        assert result["status"] == "confirmed"
        name = conn.execute(
            "SELECT name FROM molecules WHERE mol_id = 'mol-1'"
        ).fetchone()[0]
        assert name == "21"

        repo.insert_review_item(
            item_id="coref-2",
            kind="ambiguous_coref",
            doc_id="doc-1",
            payload={
                "mol_id": "mol-2",
                "ocr_labels": ["3", "21"],
                "coref_primary": "21",
            },
        )
        decide(repo, kind="ambiguous_coref", item_id="coref-2", action="confirm")
        fallback = conn.execute(
            "SELECT name FROM molecules WHERE mol_id = 'mol-2'"
        ).fetchone()[0]
        assert fallback == "21"

        repo.insert_review_item(
            item_id="coref-3",
            kind="ambiguous_coref",
            doc_id="doc-1",
            payload={
                "mol_id": "mol-3",
                "ocr_labels": ["3", "21"],
                "coref_primary": "21",
            },
        )
        decide(repo, kind="ambiguous_coref", item_id="coref-3", action="reject")
        assert (
            conn.execute(
                "SELECT status FROM review_items WHERE item_id = 'coref-3'"
            ).fetchone()[0]
            == "rejected"
        )
        assert (
            conn.execute(
                "SELECT name FROM molecules WHERE mol_id = 'mol-3'"
            ).fetchone()[0]
            == ""
        )


def test_clear_all_empties_the_queue_and_keeps_promoted_artifacts(tmp_path) -> None:
    """Clear-all removes every queue row (any status, superseded included)
    and the audit rows keyed on those entities, leaving no orphans — but it
    must not delete confirmed molecules/scaffolds."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.mol_conn() as conn:
        repo.insert_review_item(
            item_id="pending-1",
            kind="low_conf_molecule",
            doc_id="doc-1",
            smiles="CCO",
        )
        repo.insert_review_item(
            item_id="resolved-1",
            kind="smiles_correction",
            doc_id="doc-1",
        )
        conn.execute(
            "UPDATE review_items SET status = 'rejected', resolved_at = datetime('now') "
            "WHERE item_id = 'resolved-1'"
        )
        conn.execute(
            """
            INSERT INTO markush_review_candidates
                (candidate_id, source_key, doc_id, predicted_role, smiles,
                 review_status)
            VALUES ('mark-active', 'src-1', 'doc-1', 'review_required', '*CCO',
                    'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_review_candidates
                (candidate_id, source_key, doc_id, predicted_role, smiles,
                 review_status, superseded_at)
            VALUES ('mark-superseded', 'src-2', 'doc-1', 'review_required', '*CCN',
                    'rejected', datetime('now'))
            """
        )
        conn.execute(
            "INSERT INTO markush_decisions "
            "(decision_id, entity_type, entity_id, action, snapshot) "
            "VALUES ('dec-native', 'review_item', 'pending-1', 'confirm', '{}')"
        )
        conn.execute(
            "INSERT INTO markush_decisions "
            "(decision_id, entity_type, entity_id, action, snapshot) "
            "VALUES ('dec-mark', 'review_candidate', 'mark-active', 'approve', '{}')"
        )

        result = repo.clear_all()

        assert result == {"deleted_items": 2, "deleted_candidates": 2}
        assert conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM markush_review_candidates").fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM markush_decisions "
                "WHERE entity_id IN ('pending-1', 'mark-active')"
            ).fetchone()[0]
            == 0
        )

        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES ('mol-1', 'CCO', 'x')"
        )
        conn.execute(
            "INSERT INTO markush_review_candidates "
            "(candidate_id, source_key, doc_id, predicted_role, smiles) "
            "VALUES ('mark-1', 'src-1', 'doc-1', 'scaffold', '*CCO')"
        )
        repo.clear_all()

        assert (
            conn.execute("SELECT 1 FROM molecules WHERE mol_id = 'mol-1'").fetchone()
            is not None
        )


def test_structure_correction_confirm_rewrites_and_reject_leaves_structure(
    tmp_path,
) -> None:
    """Confirming a smiles_correction rewrites the structure — keeping the
    mol_id that activity/evidence/review history hang off — while a reject
    leaves the stored structure untouched."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, canonical_smiles, name) "
            "VALUES ('mol-fix', 'CCO', 'CCO', '77')"
        )
        repo.insert_review_item(
            item_id="smiles-1",
            kind="smiles_correction",
            doc_id="doc-1",
            payload={
                "mol_id": "mol-fix",
                "suggested_smiles": "CCN",
                "printed_mz": 46.065,
            },
        )

        result = decide(
            repo,
            kind="smiles_correction",
            item_id="smiles-1",
            action="confirm",
            library_root=str(tmp_path),
        )

        assert result["status"] == "confirmed"
        row = conn.execute(
            "SELECT mol_id, smiles, canonical_smiles FROM molecules "
            "WHERE mol_id = 'mol-fix'"
        ).fetchone()
        assert tuple(row) == ("mol-fix", "CCN", "CCN")
        correction = conn.execute(
            "SELECT source FROM molecule_corrections WHERE mol_id = 'mol-fix'"
        ).fetchone()
        assert correction[0] == "smiles_correction_review"

        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, canonical_smiles, name) "
            "VALUES ('mol-keep', 'CCO', 'CCO', '78')"
        )
        repo.insert_review_item(
            item_id="smiles-2",
            kind="smiles_correction",
            doc_id="doc-1",
            payload={"mol_id": "mol-keep", "suggested_smiles": "CCN"},
        )

        decide(
            repo,
            kind="smiles_correction",
            item_id="smiles-2",
            action="reject",
            library_root=str(tmp_path),
        )

        assert (
            conn.execute(
                "SELECT smiles FROM molecules WHERE mol_id = 'mol-keep'"
            ).fetchone()[0]
            == "CCO"
        )

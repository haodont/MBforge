from __future__ import annotations

from mbforge.services.review_queue import (
    clear_all,
    decide,
    insert_review_item,
    list_queue,
    stats,
)
from mbforge.storage.sqlite.database import DatabaseManager


def test_unified_queue_maps_native_and_markush_rows(tmp_path) -> None:
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        insert_review_item(
            conn,
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
        items, total = list_queue(conn, page=1, page_size=10)
        assert total == 2
        assert {item["kind"] for item in items} == {"low_conf_molecule", "markush_link"}
        assert next(item for item in items if item["id"] == "mark-1")["page"] == 1
        assert stats(conn)["pending"] == 2


def test_native_decision_updates_status_and_audit(tmp_path) -> None:
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        insert_review_item(
            conn,
            item_id="activity-1",
            kind="activity_match",
            doc_id="doc-1",
            payload={"activity_id": "a1"},
        )
        result = decide(
            conn,
            kind="activity_match",
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


def test_ambiguous_coref_confirm_adopts_chosen_label(tmp_path) -> None:
    """confirm adopts the reviewer-chosen identifier as the molecule name."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES ('mol-1', 'CCO', '')"
        )
        insert_review_item(
            conn,
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
            conn,
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


def test_ambiguous_coref_confirm_without_choice_falls_back_to_primary(tmp_path) -> None:
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES ('mol-2', 'CCO', '')"
        )
        insert_review_item(
            conn,
            item_id="coref-2",
            kind="ambiguous_coref",
            doc_id="doc-1",
            payload={
                "mol_id": "mol-2",
                "ocr_labels": ["3", "21"],
                "coref_primary": "21",
            },
        )
        decide(conn, kind="ambiguous_coref", item_id="coref-2", action="confirm")
        name = conn.execute(
            "SELECT name FROM molecules WHERE mol_id = 'mol-2'"
        ).fetchone()[0]
        assert name == "21"


def test_ambiguous_coref_reject_only_marks_item(tmp_path) -> None:
    """reject flips the review item; the molecule keeps its current name."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES ('mol-3', 'CCO', '')"
        )
        insert_review_item(
            conn,
            item_id="coref-3",
            kind="ambiguous_coref",
            doc_id="doc-1",
            payload={
                "mol_id": "mol-3",
                "ocr_labels": ["3", "21"],
                "coref_primary": "21",
            },
        )
        decide(conn, kind="ambiguous_coref", item_id="coref-3", action="reject")
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


def test_unified_markush_decision_uses_markush_lifecycle(tmp_path) -> None:
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_review_candidates
                (candidate_id, source_key, doc_id, predicted_role, smiles)
            VALUES ('mark-1', 'source-1', 'doc-1', 'review_required', '*CCO')
            """
        )

        rejected = decide(
            conn,
            kind="markush_link",
            item_id="mark-1",
            action="reject",
        )
        reopened = decide(
            conn,
            kind="markush_link",
            item_id="mark-1",
            action="reopen",
        )

    assert rejected["new_state"] == "rejected"
    assert reopened["new_state"] == "pending"


def test_reimport_preserves_native_human_decision(tmp_path) -> None:
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        insert_review_item(
            conn,
            item_id="stable-1",
            kind="low_conf_molecule",
            doc_id="doc-1",
            smiles="CCO",
        )
        decide(conn, kind="low_conf_molecule", item_id="stable-1", action="reject")

        insert_review_item(
            conn,
            item_id="stable-1",
            kind="low_conf_molecule",
            doc_id="doc-1",
            smiles="CCN",
            confidence=0.3,
        )

        row = conn.execute(
            "SELECT status, smiles, confidence FROM review_items WHERE item_id = ?",
            ("stable-1",),
        ).fetchone()
        assert tuple(row) == ("rejected", "CCN", 0.3)


def test_clear_all_empties_review_items_candidates_and_audit(tmp_path) -> None:
    """Clear-all removes every queue row (any status, superseded included)
    and the audit rows keyed on those entities, leaving no orphans."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        insert_review_item(
            conn,
            item_id="pending-1",
            kind="low_conf_molecule",
            doc_id="doc-1",
            smiles="CCO",
        )
        insert_review_item(
            conn,
            item_id="resolved-1",
            kind="activity_match",
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

        result = clear_all(conn)

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


def test_clear_all_keeps_promoted_artifacts(tmp_path) -> None:
    """Clearing the review center must not delete confirmed molecules/scaffolds."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES ('mol-1', 'CCO', 'x')"
        )
        conn.execute(
            "INSERT INTO markush_review_candidates "
            "(candidate_id, source_key, doc_id, predicted_role, smiles) "
            "VALUES ('mark-1', 'src-1', 'doc-1', 'scaffold', '*CCO')"
        )
        clear_all(conn)

        assert (
            conn.execute("SELECT 1 FROM molecules WHERE mol_id = 'mol-1'").fetchone()
            is not None
        )

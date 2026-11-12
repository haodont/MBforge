"""Tests for the unified review queue.

Covers ``service.use_cases.review_queue.decide`` (native review lifecycle,
ambiguous coreference, structure corrections) and the ``repositories.review``
contract (queue listing/stats, re-import stability, ``clear_all``).
"""

from __future__ import annotations

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.review_queue import decide


def test_queue_lists_native_items_and_reimport_preserves_human_decision(
    tmp_path,
) -> None:
    """The queue projects review_items rows, and a re-import of a resolved
    item refreshes its fields without losing the reviewer's decision."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.connection() as conn:
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
        items, total = repo.list_queue(page=1, page_size=10)
        assert total == 1
        assert {item["kind"] for item in items} == {"low_conf_molecule"}
        assert items[0]["page"] == 2
        assert repo.stats()["pending"] == 1

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


def test_decide_flips_native_review_item_status_and_writes_audit(
    tmp_path,
) -> None:
    """A native review decision flips the item's own status and appends an
    audit row keyed on the review item."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.connection() as conn:
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


def test_ambiguous_coref_confirm_adopts_choice_and_reject_only_resolves(
    tmp_path,
) -> None:
    """confirm adopts the reviewer-chosen identifier (falling back to the
    primary label); reject flips the item and keeps the molecule's name."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.connection() as conn:
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
    """Clear-all removes every queue row (any status) and the audit rows keyed
    on those review items, leaving no orphans — but it must not delete
    confirmed molecules."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    repo = get_repositories(str(tmp_path)).review
    with db.connection() as conn:
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
            "INSERT INTO markush_decisions "
            "(decision_id, entity_type, entity_id, action, snapshot) "
            "VALUES ('dec-native', 'review_item', 'pending-1', 'confirm', '{}')"
        )

        result = repo.clear_all()

        assert result == {"deleted_items": 2}
        assert conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM markush_decisions WHERE entity_id = 'pending-1'"
            ).fetchone()[0]
            == 0
        )

        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES ('mol-1', 'CCO', 'x')"
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
    with db.connection() as conn:
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

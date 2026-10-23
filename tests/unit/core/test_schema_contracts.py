"""Schema contracts for the Markush review queue, attachment sites, enumeration
and the committed patent-analysis state row.

Covers ``DatabaseManager.initialize`` DDL (``mbforge.db.sqlite.database``):
re-import identity keys that must stay unique, the indexes the review UI
queries rely on, the append-only decision audit trail, and the
``patent_analysis_state`` row shape + revision guard.
"""

from __future__ import annotations

import sqlite3

import pytest

from mbforge.db.sqlite.database import DatabaseManager


@pytest.fixture
def fresh_db(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def test_unique_identity_keys_reject_duplicate_rows(fresh_db) -> None:
    """Re-import identity keys must fail on duplicates: review-candidate
    ``source_key``, one site label per scaffold, one combination per run."""
    with fresh_db.mol_conn() as conn:
        insert_candidate = (
            "INSERT INTO markush_review_candidates "
            "(candidate_id, source_key, doc_id, predicted_role, smiles) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        conn.execute(
            insert_candidate,
            ("c1", "doc-1/page=1/bbox=fixed/lbl=R1", "doc-1", "scaffold", "*c1ccccc1*"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                insert_candidate,
                (
                    "c2",
                    "doc-1/page=1/bbox=fixed/lbl=R1",
                    "doc-1",
                    "scaffold",
                    "*c1ccccc1*",
                ),
            )

        conn.execute(
            "INSERT INTO markush_scaffolds (scaffold_id, doc_id, smiles, status) "
            "VALUES ('sc-1', 'doc-1', '*c1ccc(*)cc1', 'confirmed')"
        )
        insert_site = (
            "INSERT INTO markush_sites "
            "(site_id, scaffold_id, site_label, atom_map_num, attachment_count, status) "
            "VALUES (?, 'sc-1', 'R1', ?, 1, 'pending')"
        )
        conn.execute(insert_site, ("site-1", 1))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert_site, ("site-2", 2))

        conn.execute(
            "INSERT INTO markush_generation_runs "
            "(run_id, scaffold_id, selection, theoretical_count, requested_limit, status) "
            "VALUES ('run-1', 'sc-1', '[]', 1, 1, 'completed')"
        )
        insert_generated = (
            "INSERT INTO markush_generated_candidates "
            "(generated_id, run_id, scaffold_id, combination_key, smiles, "
            " canonical_smiles, assignments, validation_status) "
            "VALUES (?, 'run-1', 'sc-1', 'k1', ?, ?, '{}', 'valid')"
        )
        conn.execute(insert_generated, ("g-1", "F", "F"))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert_generated, ("g-2", "Cl", "Cl"))


def test_required_indexes_exist_for_ui_queries(fresh_db) -> None:
    """Evidence entity/doc lookups and attachment-site lookups are indexed."""
    with fresh_db.mol_conn() as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    assert {
        "idx_me_entity",
        "idx_me_doc",
        "idx_mst_scaffold",
        "idx_mst_label",
        "idx_mo_site",
        "idx_mmnt_site",
    } <= indexes


def test_markush_decisions_records_audit_trail(fresh_db) -> None:
    """The decisions log must accept an append-only audit row."""
    with fresh_db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO markush_review_candidates "
            "(candidate_id, source_key, doc_id, predicted_role, smiles) "
            "VALUES (?, ?, ?, ?, ?)",
            ("c-audit", "src-audit", "doc-1", "fragment", "*c1ccccc1"),
        )
        conn.execute(
            "INSERT INTO markush_decisions "
            "(decision_id, entity_type, entity_id, action, new_state, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "d1",
                "review_candidate",
                "c-audit",
                "confirm_fragment",
                "confirmed",
                "human review",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT action, new_state, reason FROM markush_decisions WHERE entity_id = ?",
            ("c-audit",),
        ).fetchone()
    assert row["action"] == "confirm_fragment"
    assert row["new_state"] == "confirmed"
    assert row["reason"] == "human review"


def test_patent_analysis_state_row_shape_and_revision_guard(fresh_db) -> None:
    """One row per document; revision starts at 1; decisions default to empty."""
    with fresh_db.mol_conn() as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(patent_analysis_state)")
        }
        assert columns == {
            "doc_id",
            "revision",
            "evidence_signature",
            "analysis_status",
            "extraction_mode",
            "payload",
            "decisions",
            "updated_at",
            "created_at",
        }

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO patent_analysis_state "
                "(doc_id, revision, evidence_signature, analysis_status, "
                " extraction_mode, payload, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("doc-1", 0, "sig", "succeeded", "hybrid", "{}", "2026-10-13"),
            )

        conn.execute(
            "INSERT INTO patent_analysis_state "
            "(doc_id, revision, evidence_signature, analysis_status, "
            " extraction_mode, payload, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("doc-1", 1, "sig", "succeeded", "hybrid", "{}", "2026-10-13"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT decisions FROM patent_analysis_state WHERE doc_id = ?", ("doc-1",)
        ).fetchone()
    assert row["decisions"] == "{}"

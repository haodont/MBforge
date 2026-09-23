"""Regression tests for the Markush review queue tables."""

from __future__ import annotations

import sqlite3

import pytest

from mbforge.adapters.persistence.sqlite.database import DatabaseManager


@pytest.fixture
def fresh_db(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    return {row[0] for row in rows}


def test_greenfield_init_creates_review_tables(fresh_db) -> None:
    """A fresh database must include the review queue tables."""
    with fresh_db.mol_conn() as conn:
        names = _table_names(conn)
    expected = {
        "markush_review_candidates",
        "markush_evidence",
        "markush_decisions",
        "molecule_corrections",
        "review_items",
    }
    assert expected.issubset(names)


def test_review_candidate_source_key_is_unique(fresh_db) -> None:
    """``source_key`` is the re-import identity — duplicates must fail."""
    with fresh_db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_review_candidates
                (candidate_id, source_key, doc_id, predicted_role, smiles)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("c1", "doc-1/page=1/bbox=fixed/lbl=R1", "doc-1", "scaffold", "*c1ccccc1*"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO markush_review_candidates
                    (candidate_id, source_key, doc_id, predicted_role, smiles)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "c2",
                    "doc-1/page=1/bbox=fixed/lbl=R1",
                    "doc-1",
                    "scaffold",
                    "*c1ccccc1*",
                ),
            )


def test_markush_evidence_indexes_entity_and_doc(fresh_db) -> None:
    """Two indexes — entity lookup + doc lookup — are required for the UI."""
    with fresh_db.mol_conn() as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    assert "idx_me_entity" in indexes
    assert "idx_me_doc" in indexes


def test_markush_decisions_records_audit_trail(fresh_db) -> None:
    """The decisions log must accept an append-only audit row."""
    with fresh_db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_review_candidates
                (candidate_id, source_key, doc_id, predicted_role, smiles)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("c-audit", "src-audit", "doc-1", "fragment", "*c1ccccc1"),
        )
        conn.execute(
            """
            INSERT INTO markush_decisions
                (decision_id, entity_type, entity_id, action, new_state, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
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

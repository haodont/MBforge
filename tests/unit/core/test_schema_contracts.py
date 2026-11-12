"""Schema contracts for the review decision audit trail and the committed
patent-analysis state row.

Covers ``DatabaseManager.initialize`` DDL (``mbforge.db.sqlite.database``):
the append-only decision audit trail and the ``patent_analysis_state`` row
shape + revision guard.
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


def test_markush_decisions_records_audit_trail(fresh_db) -> None:
    """The decisions log must accept an append-only audit row for a review
    item."""
    with fresh_db.connection() as conn:
        conn.execute(
            "INSERT INTO markush_decisions "
            "(decision_id, entity_type, entity_id, action, new_state, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "d1",
                "review_item",
                "item-audit",
                "confirm",
                "confirmed",
                "human review",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT action, new_state, reason FROM markush_decisions WHERE entity_id = ?",
            ("item-audit",),
        ).fetchone()
    assert row["action"] == "confirm"
    assert row["new_state"] == "confirmed"
    assert row["reason"] == "human review"


def test_patent_analysis_state_row_shape_and_revision_guard(fresh_db) -> None:
    """One row per document; revision starts at 1; the payload column is required."""
    with fresh_db.connection() as conn:
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
            "SELECT payload, revision FROM patent_analysis_state WHERE doc_id = ?",
            ("doc-1",),
        ).fetchone()
    assert row["payload"] == "{}"
    assert row["revision"] == 1

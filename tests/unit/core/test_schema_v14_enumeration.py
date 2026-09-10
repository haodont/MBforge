"""Regression tests for the enumeration generation tables."""

from __future__ import annotations

import sqlite3

import pytest

from mbforge.storage.sqlite.database import DatabaseManager


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


def test_greenfield_init_creates_enumeration_tables(fresh_db) -> None:
    with fresh_db.mol_conn() as conn:
        names = _table_names(conn)
    assert {"markush_generation_runs", "markush_generated_candidates"} <= names


def test_generated_candidate_unique_per_run_combination(fresh_db) -> None:
    """``UNIQUE(run_id, combination_key)`` prevents duplicate combinations."""
    with fresh_db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES ('sc-1', 'doc-test', '*c1ccc(*)cc1', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_generation_runs
                (run_id, scaffold_id, selection, theoretical_count,
                 requested_limit, status)
            VALUES ('run-1', 'sc-1', '[]', 1, 1, 'completed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_generated_candidates
                (generated_id, run_id, scaffold_id, combination_key,
                 smiles, canonical_smiles, assignments, validation_status)
            VALUES ('g-1', 'run-1', 'sc-1', 'k1', 'F', 'F', '{}', 'valid')
            """
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO markush_generated_candidates
                    (generated_id, run_id, scaffold_id, combination_key,
                     smiles, canonical_smiles, assignments, validation_status)
                VALUES ('g-2', 'run-1', 'sc-1', 'k1', 'Cl', 'Cl', '{}', 'valid')
                """
            )

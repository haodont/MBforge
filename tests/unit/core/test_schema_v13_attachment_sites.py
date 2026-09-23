"""Regression tests for Markush attachment-site tables."""

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


def test_greenfield_init_creates_attachment_tables(fresh_db) -> None:
    with fresh_db.mol_conn() as conn:
        names = _table_names(conn)
    assert {"markush_sites", "markush_options", "markush_mounts"} <= names


def test_attachment_table_indexes_exist(fresh_db) -> None:
    """Required indexes for the UI queries."""
    with fresh_db.mol_conn() as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    assert "idx_mst_scaffold" in indexes
    assert "idx_mst_label" in indexes
    assert "idx_mo_site" in indexes
    assert "idx_mmnt_site" in indexes


def test_site_unique_label_per_scaffold(fresh_db) -> None:
    """Two sites on the same scaffold must have distinct labels (TODO §7.1)."""
    with fresh_db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES ('sc-1', 'doc-1', '*c1ccc(*)cc1', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_sites
                (site_id, scaffold_id, site_label, atom_map_num, attachment_count, status)
            VALUES (?, 'sc-1', 'R1', 1, 1, 'pending')
            """,
            ("site-1",),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO markush_sites
                    (site_id, scaffold_id, site_label, atom_map_num, attachment_count, status)
                VALUES (?, 'sc-1', 'R1', 2, 1, 'pending')
                """,
                ("site-2",),
            )

"""Regression tests for activities cleanup on molecule delete.

``delete_molecule_records`` issues an explicit ``DELETE FROM activities``
so the cleanup is visible and works on connections that have
``PRAGMA foreign_keys`` off.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mbforge.storage.sqlite.database import DatabaseManager


def _seed_molecule(conn: sqlite3.Connection, mol_id: str, smiles: str = "CCO") -> None:
    conn.execute(
        "INSERT INTO molecules (mol_id, smiles, esmiles, name, source_doc, "
        "source_type, status, canonical_smiles) "
        "VALUES (?, ?, ?, ?, ?, 'image', 'pending', ?)",
        (mol_id, smiles, smiles, mol_id, "doc-test", smiles),
    )


def _seed_activity(
    conn: sqlite3.Connection,
    activity_id: str,
    mol_id: str,
    value: float = 4.0,
) -> None:
    conn.execute(
        "INSERT INTO activities (activity_id, mol_id, doc_id, activity_type, "
        "value, target, assay_description) "
        "VALUES (?, ?, ?, 'IC50', ?, 'STAT6', 'hSTAT6 TR-FRET')",
        (activity_id, mol_id, "doc-test", value),
    )


def test_no_orphans_after_delete_with_foreign_keys_off(tmp_path: Path) -> None:
    """With ``PRAGMA foreign_keys = OFF`` the explicit DELETE still wins.

    The CASCADE FK is the primary safety net, but ``delete_molecule_records``
    must also work on connections that have foreign-key enforcement off —
    otherwise an existing connection setting would leave orphan activity
    rows behind even after a successful molecule delete.
    """
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        _seed_molecule(conn, "mol-1")
        _seed_molecule(conn, "mol-2")
        _seed_activity(conn, "act-1", "mol-1", value=1.0)
        _seed_activity(conn, "act-2", "mol-1", value=2.0)
        _seed_activity(conn, "act-3", "mol-2", value=3.0)
        conn.commit()

        deleted = DatabaseManager.delete_molecule_records(conn, ["mol-1"])

        # Direct orphan check: activities.mol_id must be empty after delete.
        orphan_count = conn.execute(
            "SELECT COUNT(*) AS c FROM activities "
            "WHERE mol_id NOT IN (SELECT mol_id FROM molecules)"
        ).fetchone()["c"]
        activities = conn.execute("SELECT activity_id FROM activities").fetchall()
        molecules = conn.execute("SELECT mol_id FROM molecules").fetchall()

    assert deleted == 1
    assert orphan_count == 0
    assert [r["activity_id"] for r in activities] == ["act-3"]
    assert [r["mol_id"] for r in molecules] == ["mol-2"]

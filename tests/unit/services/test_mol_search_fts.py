"""Regression tests for the mol_search FTS5 index.

Covers ``db.sqlite.database.DatabaseManager`` index maintenance
(``sync_molecule_to_mol_search`` / ``delete_molecule_from_mol_search`` /
``sync_molecule_fingerprint``) as observed through
``services.use_cases.molecule.queries.search_molecules``.
"""

from __future__ import annotations

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.service.use_cases.molecule.queries import search_molecules


def test_mol_search_index_tracks_writes_and_treats_punctuation_literally(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """The external-content FTS table mirrors insert/update/delete, and
    user-entered punctuation is matched as literal text, not FTS5 syntax."""
    root = str(tmp_path / "library")
    db = DatabaseManager.get(root)
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO molecules
                (mol_id, smiles, esmiles, name, notes, source_type, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("mol_1", "CCO", "CCO", "ethanol", "simple alcohol", "image", "pending"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, "mol_1")

    results = search_molecules(root, "ethanol", top_k=10)
    assert len(results) == 1
    assert results[0]["name"] == "ethanol"

    with db.mol_conn() as conn:
        conn.execute(
            "UPDATE molecules SET name = ?, notes = ? WHERE mol_id = ?",
            ("literal = syntax", "punctuation", "mol_1"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, "mol_1")

    results = search_molecules(root, "literal = syntax", top_k=10)
    assert [result["mol_id"] for result in results] == ["mol_1"]

    with db.mol_conn() as conn:
        DatabaseManager.delete_molecule_from_mol_search(conn, "mol_1")
        conn.execute(
            "UPDATE molecules SET name = ?, notes = ? WHERE mol_id = ?",
            ("methanol", "updated note", "mol_1"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, "mol_1")

    assert len(search_molecules(root, "literal = syntax")) == 0
    assert len(search_molecules(root, "methanol")) == 1

    with db.mol_conn() as conn:
        DatabaseManager.delete_molecule_records(conn, ["mol_1"])

    assert len(search_molecules(root, "methanol")) == 0


def test_fingerprint_populated_after_insert(tmp_path: pytest.TempPathFactory) -> None:
    """sync_molecule_fingerprint should store a packed Morgan fingerprint."""
    root = str(tmp_path / "library")
    db = DatabaseManager.get(root)
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES (?, ?, ?)",
            ("mol_1", "CCO", "ethanol"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, "mol_1")
        DatabaseManager.sync_molecule_fingerprint(conn, "mol_1")
        fp = conn.execute(
            "SELECT fingerprint FROM molecules WHERE mol_id = ?", ("mol_1",)
        ).fetchone()["fingerprint"]

    assert fp is not None
    assert len(fp) == 256

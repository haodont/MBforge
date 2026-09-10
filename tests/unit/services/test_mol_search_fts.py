"""Regression tests for the mol_search FTS5 index."""

from __future__ import annotations

import pytest

from mbforge.services.molecule.queries import search_molecules
from mbforge.storage.sqlite.database import DatabaseManager


def test_mol_search_populated_after_insert(tmp_path: pytest.TempPathFactory) -> None:
    """FTS5 external-content table must be kept in sync after molecule writes."""
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


def test_mol_search_treats_fts_syntax_as_literal_text(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """User-entered punctuation must not be interpreted as FTS5 syntax."""
    root = str(tmp_path / "library")
    db = DatabaseManager.get(root)
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name) VALUES (?, ?, ?)",
            ("mol_1", "CCO", "literal = syntax"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, "mol_1")

    results = search_molecules(root, "literal = syntax", top_k=10)

    assert [result["mol_id"] for result in results] == ["mol_1"]


def test_mol_search_update_and_delete(tmp_path: pytest.TempPathFactory) -> None:
    """Update and delete must also be reflected in mol_search."""
    root = str(tmp_path / "library")
    db = DatabaseManager.get(root)
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name, notes) VALUES (?, ?, ?, ?)",
            ("mol_1", "CCO", "ethanol", "old note"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, "mol_1")

    assert len(search_molecules(root, "ethanol")) == 1

    with db.mol_conn() as conn:
        DatabaseManager.delete_molecule_from_mol_search(conn, "mol_1")
        conn.execute(
            "UPDATE molecules SET name = ?, notes = ? WHERE mol_id = ?",
            ("methanol", "updated note", "mol_1"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, "mol_1")

    assert len(search_molecules(root, "ethanol")) == 0
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

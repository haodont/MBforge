"""Tests for molecule_recorrection.py batch recorrection functionality."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from mbforge.adapters.persistence.sqlite.database import DatabaseManager
from mbforge.application.use_cases.molecule.recorrection import (
    RecorrectionResult,
    _rebuild_molecule,
    recorrect_molecules,
)


@pytest.fixture
def temp_library():
    """Create a temporary library root with initialized database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db = DatabaseManager.get(str(root))
        db.initialize()
        yield str(root)


@pytest.fixture
def sample_molecule(temp_library):
    """Insert a sample molecule into the test database."""
    db = DatabaseManager.get(temp_library)
    mol_id = "c1ccccc1"
    properties = {
        "context_texts": ["wherein R1 is methyl"],
        "label_kind": "formula",
    }

    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO molecules
            (mol_id, smiles, esmiles, name, canonical_smiles, review_status, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mol_id,
                "c1ccccc1",
                "c1ccccc1",
                "Formula I",
                "c1ccccc1",
                "approved",
                json.dumps(properties),
            ),
        )
        conn.execute(
            """
            INSERT INTO molecule_detections
            (mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
             conf_moldet, conf_molscribe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (mol_id, "test_doc", 0, 100.0, 100.0, 200.0, 200.0, 0.9, 0.8),
        )
        conn.execute(
            """
            INSERT INTO evidence
            (canonical_smiles, mol_id, doc_id, page, context_text, kind)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mol_id, mol_id, "test_doc", 1, "Formula I compound", "figure"),
        )
        conn.commit()

    return mol_id


class TestRebuildMolecule:
    """Tests for rebuilding Molecule from database rows."""

    def test_rebuilds_basic_molecule(self, temp_library, sample_molecule):
        db = DatabaseManager.get(temp_library)
        row = db.execute(
            "SELECT * FROM molecules WHERE mol_id = ?", (sample_molecule,), db="mol"
        )[0]
        detections = db.execute(
            "SELECT * FROM molecule_detections WHERE mol_id = ?",
            (sample_molecule,),
            db="mol",
        )
        evidence = db.execute(
            "SELECT * FROM evidence WHERE mol_id = ?", (sample_molecule,), db="mol"
        )

        nm = _rebuild_molecule(row, detections, evidence)

        assert nm.canonical_smiles == "c1ccccc1"
        assert nm.name == "Formula I"
        assert nm.status == "pending"  # approved -> pending for corrector
        assert len(nm.detections) == 1
        assert nm.detections[0].page == 0
        assert "context_texts" in nm.properties

    def test_merges_evidence_context(self, temp_library, sample_molecule):
        db = DatabaseManager.get(temp_library)
        row = db.execute(
            "SELECT * FROM molecules WHERE mol_id = ?", (sample_molecule,), db="mol"
        )[0]
        detections = db.execute(
            "SELECT * FROM molecule_detections WHERE mol_id = ?",
            (sample_molecule,),
            db="mol",
        )
        evidence = db.execute(
            "SELECT * FROM evidence WHERE mol_id = ?", (sample_molecule,), db="mol"
        )

        nm = _rebuild_molecule(row, detections, evidence)

        contexts = nm.properties.get("context_texts", [])
        assert "wherein R1 is methyl" in contexts
        assert "Formula I compound" in contexts


class TestRecorrectMolecules:
    """Tests for the recorrect_molecules function."""

    def test_dry_run_does_not_update(self, temp_library, sample_molecule):
        result = recorrect_molecules(temp_library, dry_run=True)

        assert isinstance(result, RecorrectionResult)
        assert result.total_molecules == 1
        assert result.corrected_count >= 0

        # Verify database was not updated
        db = DatabaseManager.get(temp_library)
        row = db.execute(
            "SELECT review_status FROM molecules WHERE mol_id = ?",
            (sample_molecule,),
            db="mol",
        )[0]
        assert row["review_status"] == "approved"  # Unchanged

    def test_apply_updates_database(self, temp_library, sample_molecule):
        result = recorrect_molecules(temp_library, dry_run=False)

        assert result.corrected_count >= 0

        # Verify database was updated
        db = DatabaseManager.get(temp_library)
        row = db.execute(
            "SELECT review_status, properties FROM molecules WHERE mol_id = ?",
            (sample_molecule,),
            db="mol",
        )[0]
        assert row["review_status"] == "pending"  # Reset to pending

        # Should have corrections or review_flags if any rules triggered
        # (depends on whether corrector rules matched)
        properties = json.loads(row["properties"])
        assert isinstance(properties, dict)

    def test_filter_by_doc_id(self, temp_library, sample_molecule):
        result = recorrect_molecules(temp_library, doc_id="test_doc", dry_run=True)
        assert result.total_molecules == 1

        result = recorrect_molecules(temp_library, doc_id="other_doc", dry_run=True)
        assert result.total_molecules == 0

    def test_empty_database(self, temp_library):
        result = recorrect_molecules(temp_library, dry_run=True)
        assert result.total_molecules == 0
        assert result.corrected_count == 0

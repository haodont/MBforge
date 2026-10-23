"""Tests for molecule_recorrection.py batch recorrection functionality.

Covers ``services.use_cases.molecule.recorrection`` (``_rebuild_molecule``
row→domain mapping and the ``recorrect_molecules`` dry-run/apply/filter paths).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.service.use_cases.molecule.recorrection import (
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
        "role_contexts": ["wherein R1 is methyl"],
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
             conf_moldet, conf_molscribe, context_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mol_id,
                "test_doc",
                0,
                100.0,
                100.0,
                200.0,
                200.0,
                0.9,
                0.8,
                "Formula I compound",
            ),
        )
        conn.commit()

    return mol_id


def test_rebuild_molecule_restores_rows_and_merges_evidence_context(
    temp_library, sample_molecule
):
    """Rebuilding re-maps the molecule row (approved → pending for the
    corrector) and folds detection context into ``role_contexts``."""
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
        "SELECT * FROM molecule_detections WHERE mol_id = ?",
        (sample_molecule,),
        db="mol",
    )

    nm = _rebuild_molecule(row, detections, evidence)

    assert nm.canonical_smiles == "c1ccccc1"
    assert nm.name == "Formula I"
    assert nm.status == "pending"  # approved -> pending for corrector
    assert len(nm.detections) == 1
    assert nm.detections[0].page == 0
    assert "role_contexts" in nm.properties

    contexts = nm.properties.get("role_contexts", [])
    assert "wherein R1 is methyl" in contexts
    assert "Formula I compound" in contexts


def test_recorrect_molecules_dry_run_leaves_rows_then_apply_updates(
    temp_library, sample_molecule
):
    """A dry run reports without touching the DB; apply resets to pending."""
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

    applied = recorrect_molecules(temp_library, dry_run=False)

    assert applied.corrected_count >= 0

    # Verify database was updated
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


def test_recorrect_molecules_filters_by_doc_and_handles_empty_library(
    tmp_path, temp_library, sample_molecule
):
    """The doc filter scopes the batch; an empty library is a zero-count run."""
    filtered = recorrect_molecules(temp_library, doc_id="test_doc", dry_run=True)
    assert filtered.total_molecules == 1

    excluded = recorrect_molecules(temp_library, doc_id="other_doc", dry_run=True)
    assert excluded.total_molecules == 0

    empty_root = str(tmp_path / "empty")
    DatabaseManager.get(empty_root).initialize()
    empty = recorrect_molecules(empty_root, dry_run=True)
    assert empty.total_molecules == 0
    assert empty.corrected_count == 0

"""Molecule evaluator smoke tests for the WO2026037254A1 golden."""

from __future__ import annotations

from tests.eval._lib.molecule import score_molecules


def test_score_molecules_empty(golden_reference):
    golden = golden_reference["activity_rows"]
    metrics = score_molecules(golden, {"molecules": []})
    assert metrics.matched == 0
    assert metrics.label_recall == 0.0


def test_score_molecules_perfect(golden_reference):
    golden = golden_reference["activity_rows"]
    candidate = {
        "molecules": [
            {
                "compound_label": row["compound_label"],
                "pdf_page": row["pdf_page"],
                "structure_image_present": bool(row.get("structure_image_present")),
                "molecule_role": row.get("molecule_role"),
                "smiles_canonical": row.get("smiles_canonical"),
            }
            for row in golden
        ]
    }
    metrics = score_molecules(golden, candidate)
    assert metrics.matched == len(golden)
    assert metrics.label_recall == 1.0
    assert metrics.role_accuracy == 1.0


def test_runtime_roles_respect_review_required_anchors(golden_reference):
    golden = golden_reference["concrete_molecule_anchors"]
    candidate = {
        "molecules": [
            {
                "compound_label": row["compound_label"],
                "pdf_page": row["pdf_page"],
                "structure_image_present": True,
                "molecule_role": (
                    "review_required" if row["expected_review_required"] else "complete"
                ),
            }
            for row in golden
        ]
    }

    metrics = score_molecules(golden, candidate)
    assert metrics.role_accuracy == 1.0

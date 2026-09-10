"""Activity evaluator smoke tests for the US20260027089A1 golden.

The scoring logic lives in ``tests.eval._lib.activity``. This module
binds the golden reference to the shared scorer and verifies the empty /
perfect / drift-candidate invariants.
"""

from __future__ import annotations

from tests.eval._lib.activity import score_activity


def test_score_activity_empty_candidate(golden_reference):
    golden = golden_reference["activity_rows"]
    metrics = score_activity(golden, {"results": []})
    assert metrics.matched == 0
    assert metrics.label_recall == 0.0
    assert metrics.unmatched_golden == len(golden)


def test_score_activity_perfect_candidate(golden_reference):
    golden = golden_reference["activity_rows"]
    candidate = {
        "results": [
            {
                "compound_label": row["compound_label"],
                "pdf_page": row["pdf_page"],
                "value_original": row["value_original"],
                "value_canonical_nm": row["value_canonical_nm"],
                "target": row["target"],
                "metric": row["metric"],
            }
            for row in golden
        ]
    }
    metrics = score_activity(golden, candidate)
    assert metrics.matched == len(golden)
    assert metrics.label_recall == 1.0
    assert metrics.pdf_page_accuracy == 1.0
    assert metrics.value_exact_accuracy == 1.0
    assert metrics.value_canonical_nm_accuracy == 1.0
    assert metrics.target_context_accuracy == 1.0
    assert metrics.row_alignment_accuracy == 1.0


def test_score_activity_value_drift(golden_reference):
    """A drift of 0.1 in pIC50 must drop value_exact_accuracy to 0."""
    golden = golden_reference["activity_rows"]
    candidate = {
        "results": [
            {
                "compound_label": row["compound_label"],
                "pdf_page": row["pdf_page"],
                "value_original": row["value_original"] + 0.1,
                "value_canonical_nm": row["value_canonical_nm"],
                "target": row["target"],
                "metric": row["metric"],
            }
            for row in golden
        ]
    }
    metrics = score_activity(golden, candidate)
    assert metrics.value_exact_accuracy == 0.0
    assert metrics.label_recall == 1.0

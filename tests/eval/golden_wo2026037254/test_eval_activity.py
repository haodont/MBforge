"""Activity evaluator smoke tests for the WO2026037254A1 golden.

WO activity rows use ``<`` (less-than) IC50 boundaries instead of exact
pIC50 values. The drift test in this module verifies the scorer is
strict about operator equality — ``<500`` must not match `500`.
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
                "operator_original": row["operator_original"],
            }
            for row in golden
        ]
    }
    metrics = score_activity(golden, candidate)
    assert metrics.matched == len(golden)
    assert metrics.label_recall == 1.0
    assert metrics.pdf_page_accuracy == 1.0
    assert metrics.value_exact_accuracy == 1.0
    assert metrics.target_context_accuracy == 1.0


def test_score_activity_operator_strict(golden_reference):
    """A drift in operator (< → =) drops row_alignment_accuracy below 1.0."""
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
                # force a wrong operator to verify the smoke test distinguishes.
                "operator_original": "=",
            }
            for row in golden
        ]
    }
    metrics = score_activity(golden, candidate)
    # target/metric still match so target_context_accuracy stays 1.0, but the
    # boundary operator and full row alignment must fail.
    assert metrics.label_recall == 1.0
    assert metrics.matched == len(golden)
    assert metrics.operator_accuracy == 0.0
    assert metrics.row_alignment_accuracy == 0.0

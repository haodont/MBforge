"""Markush evaluator smoke tests for the US20260027089A1 golden."""

from __future__ import annotations

from tests.eval._lib.markush import score_markush


def test_markush_zero_leakage_is_satisfied(golden_reference):
    """A perfect run must keep leakage_rate at 0."""
    golden = golden_reference["markush_anchors"]
    candidate = {
        "molecules": [
            {
                "compound_label": anchor["label"],
                "pdf_page": anchor["pdf_page"],
                "molecule_role": anchor["role"],
            }
            for anchor in golden
        ]
    }
    metrics = score_markush(golden, candidate)
    assert metrics.leakage_count == 0
    assert metrics.leakage_rate == 0.0
    assert metrics.recall == 1.0
    assert metrics.anchors_recovered == len(golden)


def test_markush_leakage_detected(golden_reference):
    """A concrete classification on Formula I must be flagged as leakage."""
    golden = golden_reference["markush_anchors"]
    candidate = {
        "molecules": [
            {
                "compound_label": anchor["label"],
                "pdf_page": anchor["pdf_page"],
                "molecule_role": "concrete",  # wrong
            }
            for anchor in golden
        ]
    }
    metrics = score_markush(golden, candidate)
    assert metrics.leakage_count == len(golden)
    assert metrics.leakage_rate == 1.0

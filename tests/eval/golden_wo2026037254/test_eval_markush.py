"""Markush evaluator smoke tests for the WO2026037254A1 golden.

The WO document exposes Formula I-IX plus R-group and claim anchors
(4 anchors total). Markush leakage must be 0 for the smoke checks to
pass.
"""

from __future__ import annotations

from tests.eval._lib.markush import score_markush


def test_markush_zero_leakage_is_satisfied(golden_reference):
    golden = golden_reference["markush_anchors"]
    # Filter to anchors with a numeric pdf_page; text-only anchors
    # (e.g. "Formula (I) definitions and R-group catalog") do not have a
    # single page and must not appear in a per-page candidate.
    anchors_with_page = [a for a in golden if isinstance(a.get("pdf_page"), int)]
    candidate = {
        "molecules": [
            {
                "compound_label": anchor["label"],
                "pdf_page": anchor["pdf_page"],
                "molecule_role": anchor["role"],
            }
            for anchor in anchors_with_page
        ]
    }
    metrics = score_markush(golden, candidate)
    assert metrics.leakage_count == 0
    assert metrics.leakage_rate == 0.0
    assert metrics.anchors_recovered == len(anchors_with_page)
    assert metrics.anchors_total == len(golden)


def test_markush_leakage_detected(golden_reference):
    golden = golden_reference["markush_anchors"]
    anchors_with_page = [a for a in golden if isinstance(a.get("pdf_page"), int)]
    candidate = {
        "molecules": [
            {
                "compound_label": anchor["label"],
                "pdf_page": anchor["pdf_page"],
                "molecule_role": "concrete",  # wrong: must stay markush
            }
            for anchor in anchors_with_page
        ]
    }
    metrics = score_markush(golden, candidate)
    assert metrics.leakage_count == len(anchors_with_page)
    assert metrics.leakage_rate == len(anchors_with_page) / len(golden)


def test_runtime_non_concrete_roles_are_safe(golden_reference):
    golden = golden_reference["markush_anchors"]
    anchors_with_page = [a for a in golden if isinstance(a.get("pdf_page"), int)]
    candidate = {
        "molecules": [
            {
                "compound_label": anchor["label"],
                "pdf_page": anchor["pdf_page"],
                "molecule_role": "review_required",
            }
            for anchor in anchors_with_page
        ]
    }

    metrics = score_markush(golden, candidate)
    assert metrics.leakage_count == 0
    assert metrics.role_classification_accuracy == 1.0

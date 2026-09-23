"""Unit tests for coreference label normalization.

The extractor upstream produces labels in many OCR-derived forms:

- "R₁", "R1", "R 2", "R₂" — numbered R-groups
- "Formula I", "formula ii", "FORMULA IV" — formula designations
- "A1", "A₂" — A-labelled rings/attachment fragments
- "3a", "12b" — example/compound numbering

Downstream persistence must read a single stable shape
``raw_coref_label`` / ``normalized_label`` / ``label_kind``. The
mapping lives in ``mbforge.application.pipeline.detection.label_normalization``.
"""

from __future__ import annotations

import pytest

from mbforge.application.pipeline.detection.label_normalization import (
    LABEL_KINDS,
    LabelKind,
    NormalizedLabel,
    normalize_coref_label,
)


@pytest.mark.parametrize(
    "raw, expected_kind, expected_normalized",
    [
        ("Formula I", LabelKind.FORMULA, "Formula I"),
        ("Formula  II", LabelKind.FORMULA, "Formula II"),
        ("formula iii", LabelKind.FORMULA, "Formula III"),
        ("FORMULA IV", LabelKind.FORMULA, "Formula IV"),
        ("Formula v", LabelKind.FORMULA, "Formula V"),
    ],
)
def test_formula_labels_normalized(
    raw: str, expected_kind: LabelKind, expected_normalized: str
) -> None:
    result = normalize_coref_label(raw)
    assert result is not None
    assert result.kind is expected_kind
    assert result.normalized == expected_normalized


@pytest.mark.parametrize(
    "raw, expected_normalized",
    [
        ("R₁", "R1"),
        ("R1", "R1"),
        ("R 2", "R2"),
        ("R₂", "R2"),
        ("R12", "R12"),
        ("R₀", "R0"),
    ],
)
def test_r_group_labels_strip_subscripts_and_spaces(
    raw: str, expected_normalized: str
) -> None:
    result = normalize_coref_label(raw)
    assert result is not None
    assert result.kind is LabelKind.R_GROUP
    assert result.normalized == expected_normalized


@pytest.mark.parametrize(
    "raw, expected_normalized",
    [
        ("A₁", "A1"),
        ("A1", "A1"),
        ("A 2", "A2"),
    ],
)
def test_ring_labels_use_ring_kind(raw: str, expected_normalized: str) -> None:
    result = normalize_coref_label(raw)
    assert result is not None
    assert result.kind is LabelKind.RING
    assert result.normalized == expected_normalized


def test_compound_label_is_numbered_letter() -> None:
    result = normalize_coref_label("3a")
    assert result is not None
    assert result.kind is LabelKind.COMPOUND
    assert result.normalized == "3a"

    result = normalize_coref_label("12b")
    assert result is not None
    assert result.kind is LabelKind.COMPOUND
    assert result.normalized == "12b"


@pytest.mark.parametrize("raw", ["化合物20", "compound 20", "20"])
def test_compound_label_prefixes_share_exact_key(raw: str) -> None:
    result = normalize_coref_label(raw)
    assert result is not None
    assert result.kind is LabelKind.COMPOUND
    assert result.normalized == "20"


def test_example_label_uses_example_kind() -> None:
    result = normalize_coref_label("Example 3")
    assert result is not None
    assert result.kind is LabelKind.EXAMPLE
    assert result.normalized == "Example 3"


@pytest.mark.parametrize("raw", ["", "   ", "???", "single"])
def test_unknown_labels_return_unknown_kind(raw: str) -> None:
    result = normalize_coref_label(raw)
    assert result is None


def test_label_kinds_is_complete() -> None:
    """The kind enum is documented in the TODO contract — guard against drift."""
    assert (
        frozenset(
            {
                LabelKind.FORMULA,
                LabelKind.R_GROUP,
                LabelKind.RING,
                LabelKind.COMPOUND,
                LabelKind.EXAMPLE,
                LabelKind.UNKNOWN,
            }
        )
        == LABEL_KINDS
    )


def test_normalized_label_preserves_raw() -> None:
    result = normalize_coref_label("R₁")
    assert isinstance(result, NormalizedLabel)
    assert result.raw == "R₁"
    assert result.normalized == "R1"

"""Unit tests for coreference label normalization.

The extractor upstream produces labels in many OCR-derived forms:

- "R₁", "R1", "R 2", "R₂" — numbered R-groups
- "Formula I", "formula ii", "FORMULA IV" — formula designations
- "A1", "A₂" — A-labelled rings/attachment fragments
- "3a", "12b" — example/compound numbering

Downstream persistence must read a single stable shape
``raw_coref_label`` / ``normalized_label`` / ``label_kind``. The
mapping lives in ``mbforge.service.pipeline.detection.label_normalization``.
"""

from __future__ import annotations

from mbforge.service.pipeline.detection.label_normalization import (
    LabelKind,
    NormalizedLabel,
    normalize_coref_label,
)

# One row per OCR spelling: (raw, expected kind, expected normalized shape).
_FORMULA_AND_EXAMPLE_LABELS: list[tuple[str, LabelKind, str]] = [
    ("Formula I", LabelKind.FORMULA, "Formula I"),
    ("Formula  II", LabelKind.FORMULA, "Formula II"),
    ("formula iii", LabelKind.FORMULA, "Formula III"),
    ("FORMULA IV", LabelKind.FORMULA, "Formula IV"),
    ("Formula v", LabelKind.FORMULA, "Formula V"),
    ("Example 3", LabelKind.EXAMPLE, "Example 3"),
]

_ATTACHMENT_AND_COMPOUND_LABELS: list[tuple[str, LabelKind, str]] = [
    # Numbered R-groups: subscripts and spaces collapse onto the digit.
    ("R₁", LabelKind.R_GROUP, "R1"),
    ("R1", LabelKind.R_GROUP, "R1"),
    ("R 2", LabelKind.R_GROUP, "R2"),
    ("R₂", LabelKind.R_GROUP, "R2"),
    ("R12", LabelKind.R_GROUP, "R12"),
    ("R₀", LabelKind.R_GROUP, "R0"),
    # A-labelled rings.
    ("A₁", LabelKind.RING, "A1"),
    ("A1", LabelKind.RING, "A1"),
    ("A 2", LabelKind.RING, "A2"),
    # Numbered examples keep their letter suffix verbatim.
    ("3a", LabelKind.COMPOUND, "3a"),
    ("12b", LabelKind.COMPOUND, "12b"),
    # Chinese and English prefixes share one exact numeric compound key.
    ("化合物20", LabelKind.COMPOUND, "20"),
    ("compound 20", LabelKind.COMPOUND, "20"),
    ("20", LabelKind.COMPOUND, "20"),
]


def test_formula_and_example_designations_keep_raw_and_normalized_shape() -> None:
    """Formula roman numerals are upper-cased; examples keep their designation."""
    for raw, expected_kind, expected_normalized in _FORMULA_AND_EXAMPLE_LABELS:
        result = normalize_coref_label(raw)
        assert result is not None, f"unrecognized label {raw!r}"
        assert isinstance(result, NormalizedLabel), f"{raw!r}"
        assert result.raw == raw, f"{raw!r}"
        assert result.kind is expected_kind, f"kind of {raw!r}"
        assert result.normalized == expected_normalized, f"normalized {raw!r}"


def test_attachment_and_compound_labels_normalize_to_the_stable_shape() -> None:
    """R-groups/rings drop subscripts and spaces; compounds share one key."""
    for raw, expected_kind, expected_normalized in _ATTACHMENT_AND_COMPOUND_LABELS:
        result = normalize_coref_label(raw)
        assert result is not None, f"unrecognized label {raw!r}"
        assert result.raw == raw, f"{raw!r}"
        assert result.kind is expected_kind, f"kind of {raw!r}"
        assert result.normalized == expected_normalized, f"normalized {raw!r}"


def test_unknown_labels_are_not_mapped() -> None:
    """Blank, punctuation-only and bare-word labels carry no coreference key."""
    for raw in ("", "   ", "???", "single"):
        assert normalize_coref_label(raw) is None, f"unexpectedly mapped {raw!r}"

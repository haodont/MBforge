"""Regression tests for activity and molecule-reference normalization.

Covers ``mbforge.service.pipeline.activity.normalization``: log/linear scale
conversion, qualitative schemes, unit handling, and the single shared
reference-label key used for activity↔molecule attribution.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mbforge.domain.patent import label_key_for
from mbforge.service.pipeline.activity.normalization import (
    canonical_value_for_legacy,
    extract_qualitative_legend,
    normalize_activity_measurement,
    normalize_activity_metric,
    normalize_reference_label,
    normalize_stored_measurement,
)

# (operator, expected comparable operator) — a log metric measures inversely.
_LOG_OPERATOR_CASES: list[tuple[str, str]] = [
    ("<", ">"),
    ("<=", ">="),
    (">=", "<="),
    ("=", "="),
]

# (raw, expected key) — every published spelling shares one compound key.
_LABEL_KEY_CASES: list[tuple[str, str]] = [
    ("化合物20", "20"),
    ("化合物 20", "20"),
    ("compound 20", "20"),
    ("20", "20"),
    ("20a", "20a"),
    ("20A", "20A"),
]


def test_log_metric_converts_to_nm_and_inverts_the_operator() -> None:
    """pIC50 becomes nM and its comparison direction flips, raw scale kept."""
    result = normalize_activity_measurement("pIC50", 6.4, "", ">")

    assert result.metric == "pIC50"
    assert result.value_original == 6.4
    assert result.value_canonical == pytest.approx(398.107, rel=1e-5)
    assert result.unit_canonical == "nM"
    assert result.scale == "log10"
    assert result.operator_original == ">"
    assert result.operator == "<"

    for operator, expected in _LOG_OPERATOR_CASES:
        inverted = normalize_activity_measurement("pIC50", 5.0, "", operator)

        assert inverted.operator_original == operator, operator
        assert inverted.operator == expected, operator
        assert inverted.value_canonical == 10_000.0, operator
        assert inverted.scale == "log10", operator

    # Unicode operators normalize before the log inversion.
    explicit = normalize_activity_measurement("pIC50", 7.0, "", "≥")
    embedded = normalize_activity_measurement("pIC50", "≤ 5.0", "")

    assert explicit.operator_original == ">="
    assert explicit.operator == "<="
    assert explicit.value_canonical == 100.0
    assert embedded.operator_original == "<="
    assert embedded.operator == ">="
    assert embedded.value_canonical == 10_000.0

    # Re-reading a stored canonical inequality must not invert it a second time.
    for original in (None, ">"):
        stored = normalize_stored_measurement(
            "pIC50",
            {
                "original_value": 7.0,
                "original_unit": "",
                "canonical_value": 100.0,
                "operator": "<",
                "operator_original": original,
            },
        )
        assert stored.operator_original == ">"
        assert stored.operator == "<"
        assert stored.value_canonical == 100.0


def test_linear_units_convert_without_inventing_concentration_units() -> None:
    """Original unit/value survive; percent and fold keep their own branch."""
    converted = normalize_activity_measurement("IC50", 1.5, "μM", "=")

    assert converted.value_original == 1.5
    assert converted.value_canonical == 1500.0
    assert converted.unit_original == "μM"
    assert converted.unit_canonical == "nM"

    for unit in ["cells/mL", "ng/mL"]:
        fallback = normalize_activity_measurement("IC50", 2.5, unit, "=")

        assert fallback.unit_original == unit, unit
        assert fallback.unit_canonical == unit, unit
        assert fallback.value_canonical == 2.5, unit
        assert fallback.scale == "linear", unit

    missing = normalize_activity_measurement("IC50", 2.5)
    assert missing.value_original == 2.5
    assert missing.value_canonical is None
    assert not missing.unit_canonical

    unicode_linear = normalize_activity_measurement("IC50", "≥ 100", "nM")

    assert unicode_linear.operator_original == ">="
    assert unicode_linear.operator == ">="
    assert unicode_linear.value_canonical == 100.0
    assert unicode_linear.scale == "linear"

    percent = normalize_activity_measurement("% inhibition", 95.0, "%", ">")

    assert percent.metric == "inhibition_pct"
    assert percent.value_original == 95.0
    assert percent.value_canonical == 95.0
    assert percent.unit_canonical == "%"
    assert percent.scale == "linear"
    assert percent.operator == ">"

    plain_percent = normalize_activity_measurement("activity", 50.0, "%", "=")

    assert plain_percent.value_canonical == 50.0
    assert plain_percent.unit_canonical == "%"
    assert plain_percent.scale == "linear"

    for unit in ["fold", "x"]:
        fold = normalize_activity_measurement("fold change", 3.2, unit, "<")

        assert fold.metric == "fold_change", unit
        assert fold.value_original == 3.2, unit
        assert fold.value_canonical == 3.2, unit
        assert fold.unit_original == unit, unit
        assert fold.unit_canonical == "fold", unit
        assert fold.scale == "linear", unit
        assert fold.operator == "<", unit


def test_qualitative_values_need_a_legend_to_be_ranked() -> None:
    """Plus grades are intrinsic; letter grades require an explicit legend."""
    plus = normalize_activity_measurement("activity", "+++", "")

    assert plus.measurement_kind == "qualitative"
    assert plus.value_original is None
    assert plus.value_canonical is None
    assert plus.qualitative_raw == "+++"
    assert plus.qualitative_rank == 3
    assert plus.qualitative_scheme == "plus"

    unresolved = normalize_activity_measurement("activity", "A", "")
    legend = extract_qualitative_legend("A = strong; B = moderate; C = weak")
    resolved = normalize_activity_measurement("activity", "A", "", legend=legend)

    assert unresolved.qualitative_scheme == "letter_unresolved"
    assert unresolved.qualitative_rank is None
    assert resolved.qualitative_scheme == "legend"
    assert resolved.qualitative_label == "strong"
    assert resolved.qualitative_rank == 3

    # ``ND`` means no data. It is not an inactivity grade and must not become
    # rank 0 (which would publish a missing cell as a measurement).
    missing = normalize_activity_measurement("activity", "ND", "")

    assert missing.qualitative_raw == "ND"
    assert missing.qualitative_rank is None
    assert missing.measurement_kind == "qualitative"


def test_metric_and_reference_labels_share_one_normalized_key() -> None:
    """OCR metric variants and every compound spelling collapse to one key."""
    assert normalize_activity_metric("pIC ₅₀") == "pIC50"
    assert normalize_activity_metric("ICso") == "IC50"

    for raw, expected in _LABEL_KEY_CASES:
        assert normalize_reference_label(raw).key == expected, raw
        assert label_key_for(raw) == expected, raw

    assert normalize_reference_label("## Compound E001").key == "E001"

    # Example designations are numbered but never compound references.
    for raw in ("Example 20", "Example 5"):
        assert normalize_reference_label(raw).reference_type == "example", raw
    assert normalize_reference_label("Example 20").key == "20"

    assert normalize_reference_label("A").ambiguous is True
    # Chinese example labels index the activity tables of CN patents.
    assert normalize_reference_label("实施例5").key == "5"
    assert normalize_reference_label("实施例5").reference_type == "example"
    assert normalize_reference_label("制备例3").key == "3"


def test_canonical_value_for_legacy_prefers_normalized_over_legacy_value() -> None:
    """The comparable value wins; missing/non-finite legacy values yield None."""
    normalized = normalize_activity_measurement("IC50", 1.5, "μM", "=")

    assert canonical_value_for_legacy(normalized) == 1500.0
    assert (
        canonical_value_for_legacy(SimpleNamespace(value_canonical=10.0, value=99.0))
        == 10.0
    )
    assert canonical_value_for_legacy(SimpleNamespace(value=2.5)) == 2.5

    qualitative = normalize_activity_measurement("activity", "+++", "")

    assert canonical_value_for_legacy(qualitative) is None
    assert canonical_value_for_legacy(SimpleNamespace(value=None)) is None
    assert canonical_value_for_legacy(SimpleNamespace(value=float("nan"))) is None
    assert canonical_value_for_legacy(SimpleNamespace(value=float("inf"))) is None
    assert canonical_value_for_legacy(SimpleNamespace()) is None

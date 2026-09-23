"""Regression tests for activity and molecule-reference normalization."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mbforge.application.pipeline.activity.normalization import (
    canonical_value_for_legacy,
    extract_qualitative_legend,
    normalize_activity_measurement,
    normalize_activity_metric,
    normalize_reference_label,
)
from mbforge.domain.patent import label_key_for


def test_pic50_is_converted_to_comparable_nm_and_preserves_raw_scale() -> None:
    result = normalize_activity_measurement("pIC50", 6.4, "", ">")

    assert result.metric == "pIC50"
    assert result.value_original == 6.4
    assert result.value_canonical == pytest.approx(398.107, rel=1e-5)
    assert result.unit_canonical == "nM"
    assert result.scale == "log10"
    assert result.operator_original == ">"
    assert result.operator == "<"


def test_activity_units_convert_without_losing_original_unit() -> None:
    result = normalize_activity_measurement("IC50", 1.5, "μM", "=")

    assert result.value_original == 1.5
    assert result.value_canonical == 1500.0
    assert result.unit_original == "μM"
    assert result.unit_canonical == "μM"


def test_qualitative_plus_value_is_not_treated_as_numeric() -> None:
    result = normalize_activity_measurement("activity", "+++", "")

    assert result.measurement_kind == "qualitative"
    assert result.value_original is None
    assert result.value_canonical is None
    assert result.qualitative_raw == "+++"
    assert result.qualitative_rank == 3
    assert result.qualitative_scheme == "plus"


def test_letter_grade_requires_explicit_legend() -> None:
    unresolved = normalize_activity_measurement("activity", "A", "")
    legend = extract_qualitative_legend("A = strong; B = moderate; C = weak")
    resolved = normalize_activity_measurement("activity", "A", "", legend=legend)

    assert unresolved.qualitative_scheme == "letter_unresolved"
    assert unresolved.qualitative_rank is None
    assert resolved.qualitative_scheme == "legend"
    assert resolved.qualitative_label == "strong"
    assert resolved.qualitative_rank == 3


def test_metric_and_reference_ocr_variants_are_normalized() -> None:
    assert normalize_activity_metric("pIC ₅₀") == "pIC50"
    assert normalize_activity_metric("ICso") == "IC50"

    assert normalize_reference_label("## Compound E001").key == "E001"
    assert normalize_reference_label("Example 5").reference_type == "example"
    assert normalize_reference_label("A").ambiguous is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("化合物20", "20"),
        ("化合物 20", "20"),
        ("compound 20", "20"),
        ("20", "20"),
        ("20a", "20a"),
        ("20A", "20A"),
    ],
)
def test_compound_label_key_is_shared_and_exact(raw: str, expected: str) -> None:
    assert normalize_reference_label(raw).key == expected
    assert label_key_for(raw) == expected


def test_example_label_does_not_become_compound_reference() -> None:
    reference = normalize_reference_label("Example 20")
    assert reference.key == "20"
    assert reference.reference_type == "example"


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("<", ">"), ("<=", ">="), (">=", "<="), ("=", "=")],
)
def test_log_metric_operator_is_inverted_for_comparable_concentration(
    operator: str, expected: str
) -> None:
    result = normalize_activity_measurement("pIC50", 5.0, "", operator)

    assert result.operator_original == operator
    assert result.operator == expected
    assert result.value_canonical == 10_000.0
    assert result.scale == "log10"


def test_unicode_operators_normalize_before_log_inversion() -> None:
    explicit = normalize_activity_measurement("pIC50", 7.0, "", "≥")
    embedded = normalize_activity_measurement("pIC50", "≤ 5.0", "")

    assert explicit.operator_original == ">="
    assert explicit.operator == "<="
    assert explicit.value_canonical == 100.0
    assert embedded.operator_original == "<="
    assert embedded.operator == ">="
    assert embedded.value_canonical == 10_000.0


def test_unicode_operators_normalize_without_inversion_for_linear_units() -> None:
    result = normalize_activity_measurement("IC50", "≥ 100", "nM")

    assert result.operator_original == ">="
    assert result.operator == ">="
    assert result.value_canonical == 100.0
    assert result.scale == "linear"


def test_percent_metric_keeps_linear_scale_and_percent_unit() -> None:
    result = normalize_activity_measurement("% inhibition", 95.0, "%", ">")

    assert result.metric == "inhibition_pct"
    assert result.value_original == 95.0
    assert result.value_canonical == 95.0
    assert result.unit_canonical == "%"
    assert result.scale == "linear"
    assert result.operator == ">"


def test_percent_unit_routes_plain_metric_to_percent_branch() -> None:
    result = normalize_activity_measurement("activity", 50.0, "%", "=")

    assert result.value_canonical == 50.0
    assert result.unit_canonical == "%"
    assert result.scale == "linear"


@pytest.mark.parametrize("unit", ["fold", "x"])
def test_fold_units_keep_value_and_fold_unit(unit: str) -> None:
    result = normalize_activity_measurement("fold change", 3.2, unit, "<")

    assert result.metric == "fold_change"
    assert result.value_original == 3.2
    assert result.value_canonical == 3.2
    assert result.unit_original == unit
    assert result.unit_canonical == "fold"
    assert result.scale == "linear"
    assert result.operator == "<"


@pytest.mark.parametrize("unit", ["cells/mL", "ng/mL"])
def test_unknown_concentration_unit_falls_back_to_nm(unit: str) -> None:
    result = normalize_activity_measurement("IC50", 2.5, unit, "=")

    assert result.unit_original == unit
    assert result.unit_canonical == "nM"
    assert result.value_canonical == 2.5
    assert result.scale == "linear"


def test_canonical_value_for_legacy_prefers_normalized_value() -> None:
    normalized = normalize_activity_measurement("IC50", 1.5, "μM", "=")
    record = SimpleNamespace(value_canonical=10.0, value=99.0)

    assert canonical_value_for_legacy(normalized) == 1500.0
    assert canonical_value_for_legacy(record) == 10.0


def test_canonical_value_for_legacy_reads_legacy_value_field() -> None:
    assert canonical_value_for_legacy(SimpleNamespace(value=2.5)) == 2.5


def test_canonical_value_for_legacy_rejects_missing_or_non_finite_values() -> None:
    qualitative = normalize_activity_measurement("activity", "+++", "")

    assert canonical_value_for_legacy(qualitative) is None
    assert canonical_value_for_legacy(SimpleNamespace(value=None)) is None
    assert canonical_value_for_legacy(SimpleNamespace(value=float("nan"))) is None
    assert canonical_value_for_legacy(SimpleNamespace(value=float("inf"))) is None
    assert canonical_value_for_legacy(SimpleNamespace()) is None

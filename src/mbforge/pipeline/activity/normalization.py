"""Deterministic normalization helpers for extracted bioactivity values.

The LLM is responsible for locating a measurement in a table.  This module
keeps the representation of that measurement deterministic: logarithmic
potency values are converted to a comparable concentration, qualitative
symbols retain their source meaning, and compound labels are normalized only
when their prefix is unambiguous.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from ...core.patent import compound_label_key
from ...utils.logger import get_logger

logger = get_logger(__name__)

_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_OPERATOR_RE = re.compile(r"^\s*(<=|>=|<|>|=|~|≤|≥|≈)?\s*")
_METRIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?:p\s*(?:ic|ec|ed|gi|ac|cc)\s*\d+|"
    r"(?:ic|ec|ed|gi|ac|cc)\s*\d+|p\s*k[di]|k[di])"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizedActivity:
    """Canonical form of one quantitative or qualitative measurement."""

    metric: str
    measurement_kind: str
    value_original: float | None
    value_canonical: float | None
    unit_original: str
    unit_canonical: str | None
    operator_original: str
    operator: str
    scale: str
    value_text: str
    qualitative_raw: str | None
    qualitative_rank: int | None
    qualitative_scheme: str | None
    qualitative_label: str | None


@dataclass(frozen=True)
class ReferenceLabel:
    """Normalized compound reference extracted from a table row label."""

    raw: str
    key: str | None
    reference_type: str
    ambiguous: bool = False


def _compact(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"[\s_\-]+", "", text)


def normalize_activity_metric(value: object) -> str:
    """Return a stable metric name while tolerating common OCR variants."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = _compact(raw).lower()
    compact = re.sub(r"(?<=i)so$", "50", compact)
    compact = re.sub(r"(?<=c)so$", "50", compact)

    match = re.fullmatch(r"(p?)(ic|ec|ed|gi|ac|cc)(\d+)", compact)
    if match:
        return f"{match.group(1)}{match.group(2).upper()}{match.group(3)}"
    match = re.fullmatch(r"(p?)k([di])", compact)
    if match:
        return f"{match.group(1)}K{match.group(2)}"

    lowered = re.sub(r"\s+", " ", raw.lower())
    aliases = {
        "% inhibition": "inhibition_pct",
        "percent inhibition": "inhibition_pct",
        "inhibition": "inhibition_pct",
        "% activation": "activation_pct",
        "percent activation": "activation_pct",
        "activation": "activation_pct",
        "fold change": "fold_change",
        "fold": "fold_change",
        "selectivity": "selectivity",
        "activity": "activity",
        "potency": "potency",
    }
    return aliases.get(lowered, raw.strip() or "IC50")


def find_activity_metrics(text: str) -> list[str]:
    """Find metric tokens in table headers in source order."""
    return [
        normalize_activity_metric(match.group(0))
        for match in _METRIC_TOKEN_RE.finditer(text)
    ]


def is_log_potency_metric(metric: str) -> bool:
    """Return whether ``metric`` is a pIC/pEC/pKi/pKd-style log metric."""
    return bool(re.fullmatch(r"p(?:IC|EC|ED|GI|AC|CC)\d+|pK[di]", metric))


def _normalize_unit(value: object) -> str:
    unit = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = unit.lower().replace("μ", "u")
    compact = re.sub(r"\s+", "", compact)
    aliases = {
        "nm": "nM",
        "nanomolar": "nM",
        "um": "μM",
        "micromolar": "μM",
        "mm": "mM",
        "millimolar": "mM",
        "pm": "pM",
        "picomolar": "pM",
        "m": "M",
        "molar": "M",
        "%": "%",
        "percent": "%",
        "fold": "fold",
        "x": "fold",
    }
    return aliases.get(compact, unit)


def _normalize_operator(value: object) -> str:
    operator = str(value or "=").strip()
    return {"≤": "<=", "≥": ">=", "≈": "~"}.get(operator, operator or "=")


def _invert_operator(operator: str) -> str:
    return {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "="}.get(
        operator, operator
    )


def _extract_numeric(value: object) -> tuple[float | None, str, str]:
    text = str(value if value is not None else "").strip()
    operator_match = _OPERATOR_RE.match(text)
    operator = _normalize_operator(operator_match.group(1) if operator_match else "=")
    number_match = _NUMBER_RE.search(text)
    if not number_match:
        return None, operator, text
    try:
        number = float(number_match.group(0))
    except ValueError:
        return None, operator, text
    return number, operator, text


def extract_qualitative_legend(text: str) -> dict[str, str]:
    """Extract explicit ``A = ...``/``+++ : ...`` legend entries.

    The function intentionally requires an explicit separator.  It will not
    invent an ordering for ``A/B/C/D`` merely because those letters occur in a
    table.
    """
    legend: dict[str, str] = {}
    pattern = re.compile(
        r"(?<![A-Za-z])([A-D]|\+{1,4})\s*(?:=|:|[-–—])\s*"
        r"([^,;|\n]+)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        key = match.group(1).upper()
        description = " ".join(match.group(2).split()).strip(" .")
        if description:
            legend[key] = description
    return legend


def _qualitative_rank(label: str) -> int | None:
    lowered = label.lower()
    if lowered in {"inactive", "none", "negative", "na", "nd", "nt"}:
        return 0
    if lowered in {"weak", "low", "poor"}:
        return 1
    if lowered in {"moderate", "medium"}:
        return 2
    if lowered in {"strong", "high", "good", "active"}:
        return 3
    if lowered in {"very strong", "excellent"}:
        return 4
    return None


def _normalize_qualitative(
    value: object,
    *,
    legend: Mapping[str, str] | None = None,
) -> tuple[str, int | None, str, str]:
    raw = str(value if value is not None else "").strip()
    normalized = raw.upper()
    if re.fullmatch(r"\+{1,4}", normalized):
        return raw, len(normalized), "plus", raw

    mapped = legend.get(normalized, "") if legend else ""
    label = mapped or raw
    rank = _qualitative_rank(label)
    if normalized in {"A", "B", "C", "D"}:
        # A-D is a local code, not a universal scale.  Keep the explicit
        # legend and leave rank unset unless the legend text itself is an
        # ordered semantic label such as "strong" or "inactive".
        return raw, rank, "legend" if mapped else "letter_unresolved", label
    if rank is not None or raw.lower() in {
        "active",
        "inactive",
        "weak",
        "moderate",
        "strong",
        "na",
        "nd",
        "nt",
    }:
        return raw, rank, "word", label
    return raw, None, "qualitative_unresolved", label


def normalize_activity_measurement(
    metric: object,
    value: object,
    unit: object = "",
    operator: object = "=",
    *,
    value_text: object | None = None,
    legend: Mapping[str, str] | None = None,
) -> NormalizedActivity:
    """Normalize one LLM item without guessing missing structural data."""
    canonical_metric = normalize_activity_metric(metric)
    original_unit = str(unit or "").strip()
    canonical_unit = _normalize_unit(original_unit)
    numeric, embedded_operator, text = _extract_numeric(value)
    explicit_operator = _normalize_operator(operator)
    operator_original = (
        embedded_operator
        if embedded_operator != "=" and explicit_operator == "="
        else explicit_operator
    )
    source_text = str(value_text if value_text is not None else value or text).strip()

    if numeric is None:
        qualitative_raw, rank, scheme, label = _normalize_qualitative(
            value, legend=legend
        )
        return NormalizedActivity(
            metric=canonical_metric,
            measurement_kind="status"
            if scheme == "word" and rank == 0
            else "qualitative",
            value_original=None,
            value_canonical=None,
            unit_original=original_unit,
            unit_canonical=canonical_unit or None,
            operator_original=operator_original,
            operator=operator_original,
            scale="ordinal",
            value_text=source_text,
            qualitative_raw=qualitative_raw or None,
            qualitative_rank=rank,
            qualitative_scheme=scheme,
            qualitative_label=label or None,
        )

    if is_log_potency_metric(canonical_metric):
        canonical_value = 10 ** (9 - numeric)
        canonical_unit = "nM"
        canonical_operator = _invert_operator(operator_original)
        return NormalizedActivity(
            metric=canonical_metric,
            measurement_kind="quantitative",
            value_original=numeric,
            value_canonical=canonical_value,
            unit_original=original_unit,
            unit_canonical=canonical_unit,
            operator_original=operator_original,
            operator=canonical_operator,
            scale="log10",
            value_text=source_text,
            qualitative_raw=None,
            qualitative_rank=None,
            qualitative_scheme=None,
            qualitative_label=None,
        )

    if canonical_metric.endswith("_pct") or canonical_unit == "%":
        return NormalizedActivity(
            metric=canonical_metric,
            measurement_kind="quantitative",
            value_original=numeric,
            value_canonical=numeric,
            unit_original=original_unit,
            unit_canonical="%",
            operator_original=operator_original,
            operator=operator_original,
            scale="linear",
            value_text=source_text,
            qualitative_raw=None,
            qualitative_rank=None,
            qualitative_scheme=None,
            qualitative_label=None,
        )

    if canonical_unit == "fold":
        return NormalizedActivity(
            metric=canonical_metric,
            measurement_kind="quantitative",
            value_original=numeric,
            value_canonical=numeric,
            unit_original=original_unit,
            unit_canonical="fold",
            operator_original=operator_original,
            operator=operator_original,
            scale="linear",
            value_text=source_text,
            qualitative_raw=None,
            qualitative_rank=None,
            qualitative_scheme=None,
            qualitative_label=None,
        )

    unit_for_conversion = canonical_unit or "nM"
    conversion = {
        "nM": 1.0,
        "μM": 1000.0,
        "mM": 1_000_000.0,
        "pM": 0.001,
        "M": 1_000_000_000.0,
    }.get(unit_for_conversion)
    if conversion is None:
        logger.warning(
            "Unknown unit %r; falling back to nM; %s",
            original_unit,
            source_text,
        )
        conversion = 1.0
        canonical_unit = "nM"
    return NormalizedActivity(
        metric=canonical_metric,
        measurement_kind="quantitative",
        value_original=numeric,
        value_canonical=numeric * conversion,
        unit_original=original_unit,
        unit_canonical=canonical_unit,
        operator_original=operator_original,
        operator=operator_original,
        scale="linear",
        value_text=source_text,
        qualitative_raw=None,
        qualitative_rank=None,
        qualitative_scheme=None,
        qualitative_label=None,
    )


def normalize_reference_label(value: object) -> ReferenceLabel:
    """Normalize common compound labels while retaining ambiguity metadata."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    cleaned = re.sub(r"^[#\s>*•·-]+", "", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(".。 ")

    example_match = re.fullmatch(
        r"(?i)example\s*#?\s*(E?\d+[A-Za-z]?)", cleaned
    )
    if example_match:
        return ReferenceLabel(raw, example_match.group(1), "example")

    key = compound_label_key(cleaned)
    if key is not None:
        explicit_compound = bool(
            re.match(r"(?i)^(?:化合物|compound|cmpd|cpd)", cleaned)
        )
        reference_type = (
            "compound"
            if explicit_compound or not key.upper().startswith("E")
            else "e_series"
        )
        return ReferenceLabel(raw, key, reference_type)

    token_match = re.fullmatch(r"(?i)([A-D])", cleaned)
    if token_match:
        return ReferenceLabel(raw, token_match.group(1).upper(), "letter_ambiguous", True)

    return ReferenceLabel(raw, None, "unresolved", True)


def canonical_value_for_legacy(record: object) -> float | None:
    """Return the comparable activity value for a record.

    This is the single canonical accessor shared by both persistence chains
    (``persist_molecules.py`` and ``persist_activities.py``); it must NOT be
    removed as "dead code". ``value_canonical`` is the canonical field
    produced by :func:`normalize_activity_measurement`; the ``value``
    fallback covers records that only populate the raw comparable field
    (normal extraction sets ``value`` to the same canonical nM as
    ``value_canonical``).
    """
    value = getattr(record, "value_canonical", None)
    if value is not None:
        return float(value)
    value = getattr(record, "value", None)
    return float(value) if value is not None and math.isfinite(float(value)) else None

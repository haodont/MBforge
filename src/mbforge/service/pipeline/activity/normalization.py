"""Deterministic normalization helpers for extracted bioactivity values.

Extractors locate a measurement in the source evidence. This module
keeps the representation of that measurement deterministic: logarithmic
potency values are converted to a comparable concentration, qualitative
symbols retain their source meaning, and compound labels are normalized only
when their prefix is unambiguous.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from mbforge.domain.activity import is_log_potency_metric
from mbforge.domain.patent import compound_label_key

_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_OPERATOR_RE = re.compile(r"^\s*(<=|>=|<|>|=|~|≤|≥|≈)?\s*")
#: Metric tokens found in a table header, in source order. Besides the
#: concentration-style tokens this recognizes the words that *name* an activity in
#: the CN/WO corpus — ``CYP3A4(咪达唑仑)抑制率(%)``, ``MRGPRX2 抑制``,
#: ``MRGPRX2拮抗活性``, ``抑制% (300 nM)``. The table gate (``_ACTIVITY_HEADER_RE``)
#: already accepts those headers, so without these words the layout found no metric
#: column and refused the whole table: 26 of the corpus's 31 activity tables, 24
#: measurements in one document. Longest word first, so ``抑制率`` beats ``抑制``.
METRIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?:p\s*(?:ic|ec|ed|gi|ac|cc)\s*\d+|"
    r"(?:ic|ec|ed|gi|ac|cc)\s*\d+|p\s*k[di]|k[di])"
    r"(?![A-Za-z])|"
    r"抑制率|抑制活性|激动活性|拮抗活性|结合活性|抑制|激动|拮抗|活性|"
    r"(?<![A-Za-z])(?:inhibition|activation|potency|activity|response)(?![A-Za-z])|"
    # Pharmacokinetic endpoints. A published PK table names its endpoint in the
    # header (``Cmax (ng/mL)``, ``AUC0-t (h*ng/mL)``, ``半衰期(T1/2,min)``);
    # without these tokens the table carries no activity signal at all and is
    # never read.
    r"(?<![A-Za-z])(?:Cmax|AUC0?-?t|T1/2)(?![A-Za-z])|"
    r"半衰期\s*\(?\s*T1/2|半衰期",
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

    # Pharmacokinetic endpoints keep one name each, however the header spells
    # them (``Cmax``, ``AUC0-t``, ``AUC``, ``半衰期(T1/2,min)``).
    if compact.startswith("半衰期") or compact.startswith("t1/2"):
        return "T1/2"
    if compact.startswith("auc0"):
        return "AUC0-t"
    if compact == "auc":
        return "AUC"
    if compact == "cmax":
        return "Cmax"

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
        for match in METRIC_TOKEN_RE.finditer(text)
    ]


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
        "ng/ml": "ng/mL",
        "h*ng/ml": "h*ng/mL",
        "min": "min",
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
    """Extract explicit ``A = ...``/``A表示...``/``+++ : ...`` legend entries.

    The function intentionally requires an explicit separator.  It will not
    invent an ordering for ``A/B/C/D`` merely because those letters occur in a
    table.
    """
    legend: dict[str, str] = {}
    # Published legends quote their bin symbol and separate it with a full-width
    # colon (``注：“+”：IC50>1μM``), so quotes are optional noise around the key.
    # A CN patent also states its bins in prose (``其中A表示IC50值≤100nM``), where
    # the word ``表示`` plays the separator's part.
    pattern = re.compile(
        r"[“\"'(\[]?\s*(?<![A-Za-z])([A-D]|\+{1,4}|[十]{1,4})\s*[”\"')\]]?\s*"
        r"(?:=|＝|:|：|[-–—]|表示)\s*"
        r"([^,;，；|\n]+)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        key = match.group(1).upper().replace("十", "+")
        description = " ".join(match.group(2).split()).strip(" .")
        if description:
            legend[key] = description
    return legend


def _qualitative_rank(label: str) -> int | None:
    lowered = label.lower()
    # ``ND``/``NA``/``NT`` mean "no data", not an inactivity grade. Ranking
    # them as 0 published a missing cell as a measurement.
    if lowered in {"inactive", "none", "negative"}:
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
    """Normalize one extracted reading without inventing missing units."""
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

    conversion = {
        "nM": 1.0,
        "μM": 1000.0,
        "mM": 1_000_000.0,
        "pM": 0.001,
        "M": 1_000_000_000.0,
    }.get(canonical_unit)
    if conversion is not None:
        canonical_unit = "nM"
    return NormalizedActivity(
        metric=canonical_metric,
        measurement_kind="quantitative",
        value_original=numeric,
        value_canonical=(
            numeric * conversion
            if conversion is not None
            else numeric
            if canonical_unit
            else None
        ),
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


def normalize_stored_measurement(
    metric: object, value: Mapping[str, object]
) -> NormalizedActivity:
    """Normalize original fields once, including older canonical comparators."""
    operator = value.get("operator_original")
    if not operator:
        operator = value.get("operator") or "="
        # Older rule snapshots kept only the comparator on the converted value.
        if (
            is_log_potency_metric(str(metric or ""))
            and value.get("canonical_value") is not None
        ):
            operator = _invert_operator(str(operator))
    number = value.get("original_value")
    if number is None:
        number = value.get("qualitative_value") or value.get("raw_text") or ""
    return normalize_activity_measurement(
        metric,
        number,
        value.get("original_unit", ""),
        operator,
        value_text=value.get("raw_text", ""),
    )


def normalize_reference_label(value: object) -> ReferenceLabel:
    """Normalize common compound labels while retaining ambiguity metadata."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    cleaned = re.sub(r"^[#\s>*•·-]+", "", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(".。 ")

    example_match = re.fullmatch(
        r"(?i)(?:example\s*#?\s*|实施例\s*|制备例\s*|对比例\s*)"
        r"(E?\d+[A-Za-z]?(?:-[A-Za-z0-9]{1,3})?)"
        r"(?:\s*组分\s*(\d+))?",
        cleaned,
    )
    if example_match:
        component = example_match.group(2)
        if component:
            return ReferenceLabel(
                raw, f"{example_match.group(1)}组分{component}", "example"
            )
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
        return ReferenceLabel(
            raw, token_match.group(1).upper(), "letter_ambiguous", True
        )

    return ReferenceLabel(raw, None, "unresolved", True)

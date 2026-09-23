from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from mbforge.application.pipeline.activity.normalization import (
    normalize_activity_measurement,
    normalize_activity_metric,
    normalize_reference_label,
)
from mbforge.application.pipeline.activity.parsing import (
    _html_table_to_markdown,
    _is_activity_table,
    _parse_simple_activity_table,
    _simple_activity_table_is_complete,
)
from mbforge.domain.activity import (
    ActivityMeasurement,
    MeasurementValue,
    measurement_id,
)
from mbforge.domain.evidence import SourceEvidence
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.activity.extraction")


@dataclass
class ActivityRecord:
    """Record shape still consumed by the existing matching/persistence code."""

    activity_type: str
    value: float | None
    value_original: float | None
    unit: str
    operator: str
    target: str | None
    assay_type: str | None
    raw_text: str
    confidence: float
    page_num: int | None
    evidence_kind: str
    evidence_bbox: dict[str, float] | None
    table_idx: int | None = None
    row_idx: int | None = None
    col_idx: int | None = None
    row_label: str | None = None
    row_smiles: str | None = None
    measurement_kind: str = "quantitative"
    metric: str | None = None
    value_canonical: float | None = None
    unit_canonical: str | None = None
    operator_original: str | None = None
    scale: str = "linear"
    value_text: str = ""
    qualitative_raw: str | None = None
    qualitative_rank: int | None = None
    qualitative_scheme: str | None = None
    qualitative_label: str | None = None
    reference_raw: str | None = None
    reference_key: str | None = None
    reference_type: str | None = None

    def __post_init__(self) -> None:
        if self.metric is None:
            self.metric = self.activity_type
        if self.value_canonical is None:
            self.value_canonical = self.value
        if self.unit_canonical is None:
            self.unit_canonical = self.unit or None
        if self.operator_original is None:
            self.operator_original = self.operator
        if self.reference_raw is None and self.row_label is not None:
            reference = normalize_reference_label(self.row_label)
            self.reference_raw = reference.raw
            self.reference_key = reference.key
            self.reference_type = reference.reference_type


_PROSE_METRIC_RE = re.compile(
    r"(?<![A-Za-z])(?P<metric>p?\s*(?:IC|EC|ED|GI|AC|CC)\s*\d+|"
    r"p?\s*K[di])(?=$|[^A-Za-z])",
    re.IGNORECASE,
)
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_PROSE_VALUE_RE = re.compile(
    rf"(?P<operator><=|>=|<|>|=|~|≤|≥|≈)?\s*"
    rf"(?P<number>{_NUMBER})"
    rf"(?P<range>\s*(?:[-–—]|to)\s*{_NUMBER})?\s*"
    rf"(?P<unit>nM|μM|uM|mM|pM|M|%|fold|x|nanomolar|micromolar|"
    rf"millimolar|picomolar|molar)?(?=$|[^A-Za-z])",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(
    r"(?:化合物\s*[A-Za-z]?\d+[A-Za-z]?|"
    r"(?:compound|cmpd|cpd|example)\s*#?\s*[A-Za-z]?\d+[A-Za-z]?)",
    re.IGNORECASE,
)
_ACTIVITY_SIGNAL_RE = re.compile(
    r"%?\s*(?:inhibition|activation|potency|activity|response)\b|"
    r"\b(?:active|inactive|weak|moderate|strong)\b",
    re.IGNORECASE,
)
_KNOWN_UNITS = {"nm", "um", "mm", "pm", "m", "%", "fold", "x"}


def _build_activity_record(
    item: dict[str, Any],
    *,
    table_idx: int,
    page_num: int | None,
    header_metric: str | None,
    legend: dict[str, str],
    default_target: str | None = None,
) -> ActivityRecord:
    """Build the shared record shape from one deterministic table cell."""
    row_label = item.get("row_label") or item.get("reference_label")
    raw_metric = item.get("metric") or item.get("activity_type") or header_metric
    raw_value = item.get("value")
    raw_value_text = item.get("value_text")
    raw_qualitative = item.get("qualitative") or item.get("qualitative_raw")
    if raw_value is None and raw_qualitative is not None:
        raw_value = raw_qualitative
    if raw_metric == "IC50" and header_metric and header_metric.startswith("pIC"):
        raw_unit = str(item.get("unit") or "").strip()
        if not raw_unit and raw_value is not None:
            raw_metric = header_metric
    normalized = normalize_activity_measurement(
        raw_metric or "IC50",
        raw_value,
        item.get("unit", ""),
        item.get("operator", "="),
        value_text=raw_value_text,
        legend=legend,
    )
    reference = normalize_reference_label(row_label)
    return ActivityRecord(
        activity_type=normalized.metric,
        value=normalized.value_canonical,
        value_original=normalized.value_original,
        unit=normalized.unit_original or str(item.get("unit", "") or ""),
        operator=normalized.operator,
        target=item.get("target") or default_target,
        assay_type=item.get("assay_type"),
        raw_text=item.get("raw_text", "") or normalized.value_text,
        confidence=float(item.get("confidence", 0.5) or 0.5),
        page_num=page_num,
        evidence_kind="table",
        evidence_bbox=None,
        table_idx=table_idx,
        row_label=row_label,
        row_smiles=item.get("row_smiles"),
        measurement_kind=normalized.measurement_kind,
        metric=normalized.metric,
        value_canonical=normalized.value_canonical,
        unit_canonical=normalized.unit_canonical,
        operator_original=normalized.operator_original,
        scale=normalized.scale,
        value_text=normalized.value_text,
        qualitative_raw=normalized.qualitative_raw,
        qualitative_rank=normalized.qualitative_rank,
        qualitative_scheme=normalized.qualitative_scheme,
        qualitative_label=normalized.qualitative_label,
        reference_raw=reference.raw if row_label is not None else None,
        reference_key=reference.key if row_label is not None else None,
        reference_type=reference.reference_type if row_label is not None else None,
    )


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _issue(
    code: str,
    message: str,
    evidence_ids: Sequence[str],
    *,
    fact_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": "warning",
        "evidence_ids": list(evidence_ids),
        "related_fact_id": fact_id,
    }


def _provenance(reference_raw: str | None) -> dict[str, Any]:
    if not reference_raw:
        return {}
    reference = normalize_reference_label(reference_raw)
    return {
        "reference_raw": reference.raw,
        "reference_key": reference.key,
        "reference_type": reference.reference_type,
    }


def _measurement_from_record(
    doc_id: str,
    record: ActivityRecord,
    evidence_id: str,
    ids_seen: dict[str, int],
) -> ActivityMeasurement:
    metric = record.metric or record.activity_type
    raw_text = record.value_text or record.raw_text
    identity = record.row_label or ""
    base_id = measurement_id(doc_id, record.page_num, metric, raw_text, identity)
    duplicate = ids_seen.get(base_id, 0)
    ids_seen[base_id] = duplicate + 1
    resolved_measurement_id = (
        base_id
        if duplicate == 0
        else measurement_id(
            doc_id, record.page_num, metric, raw_text, f"{identity}#{duplicate}"
        )
    )
    return ActivityMeasurement(
        measurement_id=resolved_measurement_id,
        doc_id=doc_id,
        metric=metric,
        value=MeasurementValue(
            raw_text=raw_text,
            operator=record.operator,
            original_value=_decimal(record.value_original),
            original_unit=record.unit,
            canonical_value=_decimal(
                record.value_canonical
                if record.value_canonical is not None
                else record.value
            ),
            canonical_unit=record.unit_canonical or "",
            qualitative_value=record.qualitative_raw or "",
        ),
        evidence_ids=[evidence_id],
        provenance=_provenance(record.reference_raw),
    )


def _table_text(raw_text: str) -> str | None:
    stripped = raw_text.strip()
    if re.search(r"<table\b", stripped, re.IGNORECASE):
        if not re.search(r"</table\s*>", stripped, re.IGNORECASE):
            return None
        return _html_table_to_markdown(raw_text)
    if any(
        line.strip().startswith("|") and line.strip().endswith("|")
        for line in raw_text.splitlines()
    ):
        return raw_text
    return None


def _has_activity_signal(text: str) -> bool:
    return bool(
        _PROSE_METRIC_RE.search(text)
        or _ACTIVITY_SIGNAL_RE.search(text)
        or re.search(r"\b(?:nM|μM|uM|mM|pM)\b", text, re.IGNORECASE)
    )


def _known_unit(unit: str) -> bool:
    return unit.casefold().replace("μ", "u").replace(" ", "") in _KNOWN_UNITS


def _text_run(
    evidence: Sequence[SourceEvidence],
) -> tuple[str, list[tuple[int, int, SourceEvidence]]]:
    parts: list[str] = []
    spans: list[tuple[int, int, SourceEvidence]] = []
    offset = 0
    for item in evidence:
        if parts:
            parts.append("\n")
            offset += 1
        start = offset
        parts.append(item.raw_text)
        offset += len(item.raw_text)
        spans.append((start, offset, item))
    return "".join(parts), spans


def _ids_for_range(
    spans: Sequence[tuple[int, int, SourceEvidence]], start: int, end: int
) -> list[str]:
    return list(
        dict.fromkeys(
            item.evidence_id
            for block_start, block_end, item in spans
            if block_start < end and block_end > start
        )
    )


def _parse_text_run(
    doc_id: str,
    evidence: Sequence[SourceEvidence],
    measurements: list[ActivityMeasurement],
    issues: list[dict[str, Any]],
    ids_seen: dict[str, int],
) -> None:
    text, spans = _text_run(evidence)
    for metric_match in _PROSE_METRIC_RE.finditer(text):
        metric_raw = metric_match.group("metric")
        metric = normalize_activity_metric(metric_raw)
        tail = text[metric_match.end() : metric_match.end() + 160]
        value_match = _PROSE_VALUE_RE.search(tail)
        context_start = max(0, metric_match.start() - 120)
        for delimiter in ".。!?！？;；":
            context_start = max(
                context_start,
                text.rfind(delimiter, 0, metric_match.start()) + 1,
            )
        if value_match is None or re.search(
            r"[.!?。！？]", tail[: value_match.start()]
        ):
            issues.append(
                _issue(
                    "activity_value_unparsed",
                    f"could not parse {metric} value deterministically",
                    _ids_for_range(spans, context_start, metric_match.end()),
                )
            )
            continue

        unit = value_match.group("unit") or ""
        following = tail[value_match.end() :]
        if (
            value_match.group("range")
            or (not unit and re.match(r"\s*(?:[A-Za-zμ%]|/)", following))
            or (not unit and not metric.startswith("p"))
            or (unit and not _known_unit(unit))
        ):
            issue_end = metric_match.end() + value_match.end()
            issues.append(
                _issue(
                    "activity_value_unparsed",
                    f"could not normalize {metric} value deterministically",
                    _ids_for_range(spans, context_start, issue_end),
                )
            )
            continue

        value_start = metric_match.end() + value_match.start()
        value_end = metric_match.end() + value_match.end()
        raw_value = text[value_start:value_end].strip()
        normalized = normalize_activity_measurement(
            metric_raw,
            raw_value,
            unit,
            value_match.group("operator") or "=",
            value_text=raw_value,
        )
        if normalized.value_original is None:
            issues.append(
                _issue(
                    "activity_value_unparsed",
                    f"could not normalize {metric} value deterministically",
                    _ids_for_range(spans, context_start, value_end),
                )
            )
            continue

        used_ids = _ids_for_range(spans, context_start, value_end)
        source = next(
            item
            for block_start, block_end, item in spans
            if block_start < value_end and block_end >= value_start
        )
        reference_match = _REFERENCE_RE.search(
            text[context_start : metric_match.start()]
        )
        reference_raw = reference_match.group(0) if reference_match else None
        reference = normalize_reference_label(reference_raw)
        base_id = measurement_id(
            doc_id,
            source.page,
            normalized.metric,
            raw_value,
            reference.key or reference_raw or "",
        )
        duplicate = ids_seen.get(base_id, 0)
        ids_seen[base_id] = duplicate + 1
        resolved_measurement_id = (
            base_id
            if duplicate == 0
            else measurement_id(
                doc_id,
                source.page,
                normalized.metric,
                raw_value,
                f"{reference.key or reference_raw or ''}#{duplicate}",
            )
        )
        measurement = ActivityMeasurement(
            measurement_id=resolved_measurement_id,
            doc_id=doc_id,
            metric=normalized.metric,
            value=MeasurementValue(
                raw_text=raw_value,
                operator=normalized.operator,
                original_value=_decimal(normalized.value_original),
                original_unit=normalized.unit_original,
                canonical_value=_decimal(normalized.value_canonical),
                canonical_unit=normalized.unit_canonical or "",
                qualitative_value=normalized.qualitative_raw or "",
            ),
            evidence_ids=used_ids,
            provenance=_provenance(reference_raw),
        )
        measurements.append(measurement)
        if reference_raw and reference.key is None:
            issues.append(
                _issue(
                    "compound_reference_unresolved",
                    "compound reference is not unambiguous",
                    used_ids,
                    fact_id=measurement.measurement_id,
                )
            )


def extract_activity_measurements_from_evidence(
    evidence: Sequence[SourceEvidence], doc_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract serializable activity measurements from ordered SourceEvidence.

    ``text_span`` prose and complete ``table_span`` tables are parsed only from
    their ``raw_text``.  The caller supplies the already joined and validated
    evidence sequence; this function does not load SQL, files, PDF, OCR, or an
    LLM.  Each table measurement keeps the one table-level evidence ID.
    """
    measurements: list[ActivityMeasurement] = []
    issues: list[dict[str, Any]] = []
    ids_seen: dict[str, int] = {}
    text_blocks: list[SourceEvidence] = []
    table_index = 0

    def flush_text() -> None:
        if text_blocks:
            _parse_text_run(doc_id, text_blocks, measurements, issues, ids_seen)
            text_blocks.clear()

    for item in evidence:
        if item.kind == "text_span":
            if item.raw_text.strip():
                text_blocks.append(item)
            continue
        flush_text()
        if item.kind != "table_span":
            continue
        table_index += 1
        table_text = _table_text(item.raw_text)
        if table_text is None:
            if _has_activity_signal(item.raw_text):
                issues.append(
                    _issue(
                        "unsupported_table_format",
                        "activity table format is not supported",
                        [item.evidence_id],
                    )
                )
            continue
        records = _parse_simple_activity_table(
            table_text,
            table_idx=table_index - 1,
            page_num=item.page,
        )
        if not _is_activity_table(table_text) or not records:
            if _has_activity_signal(item.raw_text):
                issues.append(
                    _issue(
                        "complex_activity_table",
                        "activity table is incomplete or ambiguous",
                        [item.evidence_id],
                    )
                )
            continue
        if not _simple_activity_table_is_complete(table_text, records):
            issues.append(
                _issue(
                    "complex_activity_table",
                    "activity table contains unparsed cells",
                    [item.evidence_id],
                )
            )
            continue
        for record in records:
            measurement = _measurement_from_record(
                doc_id, record, item.evidence_id, ids_seen
            )
            measurements.append(measurement)
            if record.row_label and record.reference_key is None:
                issues.append(
                    _issue(
                        "compound_reference_unresolved",
                        "compound reference is not unambiguous",
                        [item.evidence_id],
                        fact_id=measurement.measurement_id,
                    )
                )
    flush_text()
    logger.info(
        "Activity evidence parse for %s: %d measurements, %d issues",
        doc_id,
        len(measurements),
        len(issues),
    )
    return [measurement.to_dict() for measurement in measurements], issues


__all__ = [
    "ActivityRecord",
    "extract_activity_measurements_from_evidence",
]

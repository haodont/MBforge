from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from mbforge.domain.activity import (
    ActivityMeasurement,
    MeasurementValue,
    measurement_id,
)
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import TABLE, TEXT, category_of
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.activity.normalization import (
    extract_qualitative_legend,
    normalize_activity_measurement,
    normalize_activity_metric,
    normalize_reference_label,
)
from mbforge.service.pipeline.activity.table_scan import scan_table_evidence
from mbforge.service.pipeline.detection.bbox_filter import bbox_area

logger = get_logger("mbforge.service.pipeline.activity.extraction")

#: A table region may overlap another region of the same page by a few PDF
#: points (the layout producer sometimes stores one printed table twice, once
#: cropped tight and once around it). Two boxes count as nested when one holds
#: the other within this tolerance.
_BOX_NEST_TOLERANCE = 4.0


def _box_contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    tolerance: float = _BOX_NEST_TOLERANCE,
) -> bool:
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] >= inner[2] - tolerance
        and outer[3] >= inner[3] - tolerance
    )


def _reading_key(measurement: ActivityMeasurement) -> tuple[Any, ...]:
    """The identity of a printed reading, independent of which region held it."""
    value = measurement.value
    return (
        measurement.page_num,
        measurement.metric,
        measurement.provenance.get("reference_key"),
        measurement.provenance.get("column_target"),
        value.raw_text,
        value.operator_original,
        str(value.canonical_value),
        value.canonical_unit,
    )


def _drop_duplicate_fragment_readings(
    measurements: list[ActivityMeasurement],
    evidence: Sequence[SourceEvidence],
    issues: list[dict[str, Any]],
) -> list[ActivityMeasurement]:
    """Drop the second reading of a row that two overlapping regions both hold.

    One printed table can reach the store as two table regions whose boxes lie
    inside each other; the overlapping rows are then read twice and the same
    number appears twice in the dataset. Only a reading whose two copies come
    from *nested* regions of the same page is dropped — two different tables that
    print the same value keep both copies. The dropped copy is reported as an
    issue so a reviewer can see what was removed.
    """
    boxes: dict[str, tuple[float, float, float, float]] = {}
    pages: dict[str, int] = {}
    for item in evidence:
        if item.evidence_id and item.bbox:
            boxes[item.evidence_id] = tuple(item.bbox)
            pages[item.evidence_id] = item.page

    groups: dict[tuple[Any, ...], list[ActivityMeasurement]] = {}
    for measurement in measurements:
        groups.setdefault(_reading_key(measurement), []).append(measurement)

    dropped: set[str] = set()
    for copies in groups.values():
        if len(copies) < 2:
            continue
        regions = {
            (
                pages.get(measurement.evidence_ids[0]),
                boxes.get(measurement.evidence_ids[0]),
            )
            for measurement in copies
        }
        if len(regions) != len(copies):
            # Two copies from the same region are not an overlap of regions.
            continue
        if len({page for page, _ in regions}) != 1:
            continue
        if not all(box is not None for _, box in regions):
            continue
        boxes_only = [box for _, box in regions if box is not None]
        if not any(
            _box_contains(outer, inner)
            for outer in boxes_only
            for inner in boxes_only
            if outer is not inner
        ):
            continue
        # Keep the reading from the larger region: it holds the whole table.
        keep = max(
            copies,
            key=lambda measurement: bbox_area(
                boxes.get(measurement.evidence_ids[0], (0.0, 0.0, 0.0, 0.0))
            ),
        )
        for measurement in copies:
            if measurement is keep:
                continue
            dropped.add(measurement.measurement_id)
            issues.append(
                _issue(
                    "duplicate_fragment_reading",
                    (
                        "reading of the same printed row held by two overlapping "
                        f"table regions (kept the one from the larger region; "
                        f"reference {measurement.provenance.get('reference_raw')!r}, "
                        f"value {measurement.value.raw_text!r})"
                    ),
                    list(measurement.evidence_ids),
                    fact_id=keep.measurement_id,
                    severity="info",
                )
            )
    if not dropped:
        return measurements
    return [m for m in measurements if m.measurement_id not in dropped]


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
_KNOWN_UNITS = {"nm", "um", "mm", "pm", "m", "%", "fold", "x"}

# Activity sections define their qualitative scale before the data
# (``A: IC50 < 500 nM, B: 500 nM ≤ IC50 < 1 uM``, ``注：“+”：IC50>1μM``,
# ``20nM<IC50<100nM``). Reading a bin bound as a measurement invents a value
# that no compound reported, so those occurrences are not measurements.
_SCALE_TAIL_RE = re.compile(
    rf"(?:{_NUMBER}\s*(?:nM|μM|uM|mM|pM|M|%|x)?\s*[<>≤≥＜＞]"
    rf"|[“\"'(\[]\s*\+{{1,4}}\s*[”\"')\]]\s*[:：]?"
    rf"|[<>≤≥＜＞])\s*$"
)
# A single letter is only a bin label inside an enumeration (``A: ... B: ...``).
# Scanned texts render the first letter oddly (``Λ: IC50 < 500 nM``), so the
# token is any single Latin/Greek letter rather than A-D.
_SCALE_LETTER_TAIL_RE = re.compile(r"(?<![A-Za-z])[A-Za-zΑ-Ωα-ω]\s*(?:[:：]|表示)\s*$")
_SCALE_LETTER_RE = re.compile(r"(?<![A-Za-z])[A-Za-zΑ-Ωα-ω]\s*(?:[:：]|表示)")

# A metric named so that it can be *defined* measures nothing. Claim preambles
# and glossaries ("术语“IC50”是指…", "the term ... refers to", "用語「アルキル」は…
# を包含することを意図し") use the same token the prose parser looks for.
_DEFINITION_RE = re.compile(
    r"(?:术语|用語|定義|定义)\s*[“\"'「]|"
    r"\b(?:the\s+term|as\s+used\s+herein|refers?\s+to|is\s+defined\s+as|means)\b|"
    r"是指|を意味する|を指す|を包含することを意図|의미한다",
    re.IGNORECASE,
)
# A Markush enumeration ("-CF3，-CH2-CF3，-CF2H…") is a substituent list, not a
# reading: a single compound name carries one or two fragments, never a run.
_SUBSTITUENT_FRAGMENT_RE = re.compile(r"-[A-Za-z][A-Za-z]?\d?(?=[-，,、;；\s)）]|$)")
_ALKYL_WORD_RE = re.compile(r"烷基|芳基|杂芳基|环烷基|アルキル|アリール|알킬")

# Prose that mentions a metric without reporting one. Every family below was read
# out of the corpus: scale legends (``活性范围表示如下：“A”表示…IC50<50nM``),
# glossary entries (``[0149] IC50:半数抑制浓度，指…``, ``HC 1：塩酸``), assay
# protocol text (``cells were seeded … culture medium``), literature background
# (``Tatemoto et al. have found …``), and synthesis paragraphs (``…1.0当量…``).
_LEGEND_PHRASE_RE = re.compile(r"表示如下|如下所示|如下定义|定义如下|as follows", re.I)
# A glossary entry may carry a paragraph number and OCR'd spacing
# (``[0149] IC50:半数抑制浓度``, ``D MF:N，N-ジメチルホルムアミド``).
_ENTRY_LINE_RE = re.compile(
    r"^(?:[\[\(]\s*\d{1,4}\s*[\]\)])?\s*"
    r"(?:[A-Za-z](?:[A-Za-z\s]|[\d\-]){0,4}|p?\s*(?:IC|EC|ED|GI|AC|CC)\s*\d*)"
    r"\s*[:：]\s*[^\d\n]{0,14}"
)
_PROTOCOL_LINE_RE = re.compile(
    r"接种|孵育|培养|缓冲液|每孔|室温|稀释|seeded|incubat|culture|"
    r"assay buffer|buffers?|plates?|wells?|dilut",
    re.IGNORECASE,
)
_CITATION_LINE_RE = re.compile(
    r"et al\.|have found|has been reported|prior art|参考文献|背景技术|"
    r"described in|were purchased",
    re.IGNORECASE,
)
# Mass/volume tokens survive OCR with wide spacing (``92 m g``, ``0.2 57 m mο1``).
_SYNTHESIS_LINE_RE = re.compile(
    r"合成|收率|製造例|制备例|当量|equiv|mmol|遊離塩基|at room temperature|"
    r"m\s*m\s*[οo0]?\s*1|m\s*g\s*[、,)]|\d\s*[gm]\s*[、)]",
    re.IGNORECASE,
)
# A sentence that only points at a table holds no reading of its own.
_TABLE_POINTER_RE = re.compile(
    r"shown in Table|listed in Table|示于表|见表|参见表|表\s*\d+\s*所示", re.IGNORECASE
)


def _is_scale_definition(line: str, before: str) -> bool:
    """True when the metric occurrence spells out a qualitative-bin bound."""
    if _SCALE_TAIL_RE.search(before):
        return True
    if not _SCALE_LETTER_TAIL_RE.search(before):
        return False
    return len(_SCALE_LETTER_RE.findall(line)) >= 2


def _is_definition_sentence(line: str) -> bool:
    """True when the metric occurrence only *defines* the term.

    Claim preambles and glossaries state what a metric means
    (``术语“IC50”是指…``, ``the term "IC50" refers to``, ``用語「アルキル」は…
    を包含することを意図し``). They measure nothing, so they are not a gap.
    """
    return bool(_DEFINITION_RE.search(line))


def _is_substituent_run(line: str) -> bool:
    """True when a line is a Markush list rather than a reading.

    ``-CF3，-CH2-CF3，-CF2H…`` is a substituent enumeration OCR'd out of claim
    text; a compound name carries one or two such fragments, never a list.
    """
    if len(_SUBSTITUENT_FRAGMENT_RE.findall(line)) >= 3:
        return True
    return len(_ALKYL_WORD_RE.findall(line)) >= 3


def _is_non_reading_prose(line: str) -> bool:
    """True when a line names a metric without reporting one.

    Scale legends, glossary entries, protocol text, literature background and
    synthesis paragraphs all contain the metric token the prose parser looks
    for, and none of them measures a compound.
    """
    if _LEGEND_PHRASE_RE.search(line):
        return True
    if _ENTRY_LINE_RE.match(line.strip()):
        return True
    if _CITATION_LINE_RE.search(line) or _SYNTHESIS_LINE_RE.search(line):
        return True
    if _TABLE_POINTER_RE.search(line):
        return True
    return bool(_PROTOCOL_LINE_RE.search(line) and not _REFERENCE_RE.search(line))


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
    if (
        item.get("label_space") == "example"
        and reference.key
        and reference.reference_type == "compound"
    ):
        # The column header declares the space, so a bare ``2`` under
        # ``实施例编号`` is Example 2 (``@example:2``), never the compound ``2``.
        reference = normalize_reference_label(f"Example {reference.key}")
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
    severity: str = "warning",
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "evidence_ids": list(evidence_ids),
        "related_fact_id": fact_id,
    }


def _provenance(reference_raw: str | None, target: str | None = None) -> dict[str, Any]:
    """The printed reference, plus the column the reading was taken from.

    ``target`` is the header's own assay/substrate name when the column carried one
    (``CYP3A4(咪达唑仑)抑制率(%)``). Two columns of one table can differ only there,
    and a measurement has no target field, so this is where the reading keeps the
    context a reviewer needs to tell them apart.
    """
    provenance: dict[str, Any] = {}
    if reference_raw:
        reference = normalize_reference_label(reference_raw)
        provenance = {
            "reference_raw": reference.raw,
            "reference_key": reference.key,
            "reference_type": reference.reference_type,
        }
    if target:
        provenance["column_target"] = target
    return provenance


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
            operator_original=record.operator_original or "=",
            original_value=_decimal(record.value_original),
            original_unit=record.unit,
            canonical_value=_decimal(
                record.value_canonical
                if record.value_canonical is not None
                else record.value
            ),
            canonical_unit=record.unit_canonical or "",
            qualitative_value=record.qualitative_raw or "",
            qualitative_rank=record.qualitative_rank,
            qualitative_scheme=record.qualitative_scheme or "",
            qualitative_label=record.qualitative_label or "",
        ),
        evidence_ids=[evidence_id],
        provenance=_provenance(record.reference_raw, record.target),
        measurement_kind=record.measurement_kind,
        page_num=record.page_num,
        table_idx=record.table_idx,
        row_idx=record.row_idx,
        col_idx=record.col_idx,
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
        line_start = text.rfind("\n", 0, metric_match.start()) + 1
        line_end = text.find("\n", metric_match.start())
        line = text[line_start : line_end if line_end != -1 else len(text)]
        if _is_scale_definition(line, text[line_start : metric_match.start()]):
            logger.debug("Skipping scale definition for %s: %s", doc_id, line[:120])
            continue
        if (
            _is_definition_sentence(line)
            or _is_substituent_run(line)
            or _is_non_reading_prose(line)
        ):
            logger.debug("Skipping non-reading prose for %s: %s", doc_id, line[:120])
            continue
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
            if not _REFERENCE_RE.search(text[context_start : metric_match.start()]):
                # A metric mention that names no compound is prose *about* the
                # metric, not a reading: it is not a gap either.
                continue
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
        if reference_raw is None:
            issues.append(
                _issue(
                    "activity_reference_missing",
                    f"{normalized.metric} value names no compound",
                    used_ids,
                )
            )
            continue
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
                operator_original=normalized.operator_original,
                original_value=_decimal(normalized.value_original),
                original_unit=normalized.unit_original,
                canonical_value=_decimal(normalized.value_canonical),
                canonical_unit=normalized.unit_canonical or "",
                qualitative_value=normalized.qualitative_raw or "",
                qualitative_rank=normalized.qualitative_rank,
                qualitative_scheme=normalized.qualitative_scheme or "",
                qualitative_label=normalized.qualitative_label or "",
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

    ``text``-category prose and complete ``table``-category tables are parsed
    only from their ``raw_text``.  The caller supplies the already joined and
    validated evidence sequence; this function does not load SQL, files, PDF,
    OCR, or an LLM.  Each table measurement keeps the one table-level evidence
    ID.
    """
    measurements: list[ActivityMeasurement] = []
    issues: list[dict[str, Any]] = []
    ids_seen: dict[str, int] = {}
    text_blocks: list[SourceEvidence] = []
    table_index = 0
    #: The last activity table read from its own header: its page, its evidence
    #: row and its Markdown. A fragment on the next page reuses that header: the
    #: print continues, only the header does not.
    last_activity_table: tuple[int | None, str, str] | None = None

    # A wide table that crosses a layout boundary can be stored as two evidence
    # rows whose text overlaps: the second begins with the first's content. Read
    # both and every cell in the overlap becomes a second, duplicate reading of
    # the same number. Only the longest row of such a run is read.
    table_texts = [
        (item.evidence_id, item.raw_text.strip())
        for item in evidence
        if category_of(item.kind) == TABLE and item.raw_text.strip()
    ]
    superseded: set[str] = {
        short_id
        for short_id, short_text in table_texts
        for long_id, long_text in table_texts
        if short_id != long_id and long_text.startswith(short_text)
    }

    # Qualitative bins are declared once per document (``注：“+++”20nM<IC50<100nM``)
    # and used by tables elsewhere in the document, so the legend is collected
    # from every prose block before any table is read.
    legend: dict[str, str] = {}
    for item in evidence:
        if category_of(item.kind) == TEXT and item.raw_text.strip():
            legend.update(extract_qualitative_legend(item.raw_text))

    def flush_text() -> None:
        if text_blocks:
            _parse_text_run(doc_id, text_blocks, measurements, issues, ids_seen)
            text_blocks.clear()

    for item in evidence:
        category = category_of(item.kind)
        if category == TEXT:
            if item.raw_text.strip():
                text_blocks.append(item)
            continue
        flush_text()
        if category != TABLE:
            continue
        if item.evidence_id in superseded:
            # This row's text is a prefix of a longer table row; reading it too
            # would duplicate every cell it shares with that one.
            continue
        table_index += 1
        scan = scan_table_evidence(
            item,
            table_idx=table_index - 1,
            previous=last_activity_table,
            legend=legend,
        )
        if scan.last_activity is not None:
            last_activity_table = scan.last_activity
        records = scan.records
        if scan.refusal_code is not None:
            issues.append(
                _issue(
                    scan.refusal_code,
                    scan.refusal_message,
                    list(scan.refusal_ids),
                    severity=scan.refusal_severity,
                )
            )
        if scan.gap_counts and any(scan.gap_counts.values()):
            # The rows that were read are published; the cells that named no
            # compound, or held two readings merged into one cell, are reported
            # so a partial table never reads as a complete one.
            issues.append(
                _issue(
                    "activity_cells_unattributed",
                    (f"activity table cells that became no reading: {scan.gap_counts}"),
                    [item.evidence_id],
                    severity="info",
                )
            )
        if not records:
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
    measurements = _drop_duplicate_fragment_readings(measurements, evidence, issues)
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

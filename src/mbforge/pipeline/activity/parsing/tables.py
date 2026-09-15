from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from mbforge.utils.logger import get_logger

from ..normalization import (
    extract_qualitative_legend,
    find_activity_metrics,
)

if TYPE_CHECKING:
    from ..extraction import ActivityRecord

logger = get_logger("mbforge.pipeline.activity.parsing.tables")

_NUMERIC_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_ACTIVITY_HEADER_RE = re.compile(
    r"(?<![A-Za-z])(?:p\s*(?:IC|EC|ED|GI|AC|CC)\s*\d+|"
    r"(?:IC|EC|ED|GI|AC|CC)\s*\d+|p\s*K[di]|K[di])"
    r"(?![A-Za-z])|%?\s*(?:inhibition|activation|potency|activity|response)\b|"
    r"\+{2,4}|\b(?:active|inactive|weak|moderate|strong|ND|NA|NT)\b",
    re.IGNORECASE,
)
_ACTIVITY_VALUE_RE = re.compile(
    r"(?:<|>|~|=|≤|≥)?\s*\d+(?:\.\d+)?\s*"
    r"(?:nM|μM|uM|mM|pM|M|%|fold|x)\b|"
    r"\+{2,4}|\b(?:active|inactive|weak|moderate|strong|ND|NA|NT)\b",
    re.IGNORECASE,
)
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_HEADER_UNIT_RE = re.compile(r"\b(?:nM|μM|uM|mM|pM|M|%|fold|x)\b", re.IGNORECASE)
_QUALITATIVE_CELL_RE = re.compile(
    r"^(?:\+{1,4}|active|inactive|weak|moderate|strong|nd|na|nt|[a-d])$",
    re.IGNORECASE,
)


class _HtmlTableParser(HTMLParser):
    """Collect ``<tr>/<td>`` text from an HTML table fragment."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell).split()).replace("|", "\\|")
            self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _html_table_to_markdown(html_text: str) -> str | None:
    """Convert one ``<table>`` fragment to a Markdown pipe table.

    VLM OCR backends (e.g. PaddleOCR) emit HTML tables for scanned
    documents; downstream activity parsing expects Markdown tables.
    Returns ``None`` when no usable rows are found.
    """
    parser = _HtmlTableParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # noqa: BLE001 — malformed HTML is simply skipped
        return None
    rows = parser.rows
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header, body = rows[0], rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(r) + " |" for r in body)
    return "\n".join(lines)


def _is_activity_table(table_md: str) -> bool:
    """Return whether a structurally valid table contains activity signals.

    A table is eligible when its first rows contain an activity header or any
    value with a recognized activity unit. Ambiguous tables are skipped before
    an LLM request; this keeps the full pipeline from spending remote budget
    on synthesis, characterization, or unrelated property tables.
    """
    rows = [row for row in table_md.split("\n") if row.strip()]
    if len(rows) < 2 or not any(_TABLE_SEPARATOR_RE.match(row) for row in rows[1:3]):
        return False
    sample = _normalize_table_markup("\n".join(rows[:5]))
    return bool(
        _ACTIVITY_HEADER_RE.search(sample) or _ACTIVITY_VALUE_RE.search(table_md)
    )


def _normalize_table_markup(text: str) -> str:
    """Normalize lightweight LaTeX/MathJax emitted inside table cells.

    Scanned-table OCR commonly returns headers such as
    ``${\\mathrm{{IC}}}_{50}(\\mathrm{{nM}})$``.  The semantic signal is
    still deterministic, but the raw markup does not match the activity
    header regex.  This helper only removes presentation markup; it does not
    infer a value or repair a cell.
    """
    normalized = re.sub(r"\\(?:mathrm|text|operatorname|left|right)\s*", "", str(text))
    normalized = re.sub(r"\\[A-Za-z]+\s*", " ", normalized)
    normalized = normalized.replace("{", "").replace("}", "")
    normalized = normalized.replace("$", "")
    normalized = re.sub(r"(?<=[A-Za-z])[_\s]*(?=\d)", "", normalized)
    normalized = normalized.replace("_", " ").replace("\\", " ")
    return " ".join(normalized.split())


def _split_pipe_row(line: str) -> list[str]:
    """Split one Markdown table row while preserving trimmed cell text."""
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip().replace(r"\|", "|") for cell in stripped[1:-1].split("|")]


def _activity_header_columns(
    header_cells: list[str],
) -> list[tuple[int, str, str, str | None]]:
    """Return ``(column, metric, unit, target)`` tuples from a table header."""
    columns: list[tuple[int, str, str, str | None]] = []
    for column, raw_cell in enumerate(header_cells):
        cell = _normalize_table_markup(raw_cell)
        metrics = find_activity_metrics(cell)
        if not metrics:
            continue
        metric = metrics[0]
        unit_match = _HEADER_UNIT_RE.search(cell)
        unit = unit_match.group(0) if unit_match else ""
        target = re.sub(
            r"(?i)\b(?:p?\s*(?:IC|EC|ED|GI|AC|CC)\s*\d+|p?\s*K[di])\b",
            " ",
            cell,
            count=1,
        )
        target = _HEADER_UNIT_RE.sub(" ", target)
        target = re.sub(r"[()\[\]{}$,:;]", " ", target)
        target = re.sub(
            r"(?i)\b(?:result|results|activity|assay|value|compound|number)\b",
            " ",
            target,
        )
        target = " ".join(target.split()) or None
        columns.append((column, metric, unit, target))
    return columns


def _cell_has_activity_value(cell: str) -> bool:
    """Return whether a table cell carries a quantitative/qualitative value."""
    stripped = _normalize_table_markup(cell).strip()
    return bool(
        _NUMERIC_RE.search(stripped) or _QUALITATIVE_CELL_RE.fullmatch(stripped)
    )


def _parse_simple_activity_table(
    table_md: str,
    table_idx: int,
    page_num: int | None,
    *,
    default_target: str | None = None,
) -> list[ActivityRecord]:
    """Parse a structurally simple activity table without an LLM.

    The parser is intentionally narrow: it requires a Markdown separator,
    an activity metric in the header, and a first-column row label.  Numeric
    values, comparison operators, and qualitative tokens are passed through
    the same normalization contract as LLM results.  Complex tables still
    use the LLM parser.
    """
    # Lazy import to break the parsing ↔ extraction cycle.
    # ``_build_activity_record`` lives with the LLM-orchestration path but
    # the simple-table parser produces the same record shape, so we import
    # it on first call rather than at module load.
    from ..extraction import _build_activity_record

    lines = [line for line in table_md.splitlines() if line.strip()]
    separator_index = next(
        (index for index, line in enumerate(lines) if _TABLE_SEPARATOR_RE.match(line)),
        None,
    )
    if separator_index is None or separator_index == 0:
        return []
    header_cells = _split_pipe_row(lines[separator_index - 1])
    if not header_cells:
        return []
    metric_columns = _activity_header_columns(header_cells)
    if not metric_columns:
        return []

    records: list[ActivityRecord] = []
    for line in lines[separator_index + 1 :]:
        cells = _split_pipe_row(line)
        if not cells or not cells[0]:
            continue
        row_label = cells[0]
        for column, metric, unit, header_target in metric_columns:
            if column >= len(cells) or not _cell_has_activity_value(cells[column]):
                continue
            value_text = cells[column].strip()
            target = header_target or default_target
            record = _build_activity_record(
                {
                    "metric": metric,
                    "value": value_text,
                    "value_text": value_text,
                    "unit": unit,
                    "operator": "=",
                    "target": target,
                    "raw_text": f"{row_label}: {header_cells[column]} = {value_text}",
                    "confidence": 0.98,
                    "row_label": row_label,
                },
                table_idx=table_idx,
                page_num=page_num,
                header_metric=metric,
                legend=extract_qualitative_legend(table_md),
                default_target=target,
            )
            record.col_idx = column
            records.append(record)
    return records


def _simple_activity_table_is_complete(
    table_md: str, records: list[ActivityRecord]
) -> bool:
    """Return whether every non-empty activity cell was parsed deterministically."""
    lines = [line for line in table_md.splitlines() if line.strip()]
    separator_index = next(
        (index for index, line in enumerate(lines) if _TABLE_SEPARATOR_RE.match(line)),
        None,
    )
    if separator_index is None or separator_index == 0:
        return False
    header_cells = _split_pipe_row(lines[separator_index - 1])
    metric_columns = _activity_header_columns(header_cells)
    if not metric_columns:
        return False
    expected = 0
    for line in lines[separator_index + 1 :]:
        cells = _split_pipe_row(line)
        if not cells or not cells[0]:
            continue
        expected += sum(
            1
            for column, _metric, _unit, _target in metric_columns
            if column < len(cells) and cells[column].strip()
        )
    return expected > 0 and expected == len(records)

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.activity.normalization import (
    METRIC_TOKEN_RE,
    extract_qualitative_legend,
    find_activity_metrics,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mbforge.service.pipeline.activity.extraction import ActivityRecord

logger = get_logger("mbforge.service.pipeline.activity.parsing.tables")

_NUMERIC_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_ACTIVITY_HEADER_RE = re.compile(
    r"(?<![A-Za-z])(?:p\s*(?:IC|EC|ED|GI|AC|CC)\s*\d+|"
    r"(?:IC|EC|ED|GI|AC|CC)\s*\d+|p\s*K[di]|K[di])"
    r"(?![A-Za-z])|%?\s*(?:inhibition|activation|potency|activity|response)\b|"
    r"(?:抑制|活性|抑制率|激动|拮抗)|"
    r"\+{2,4}|\b(?:active|inactive|weak|moderate|strong|ND|NA|NT)\b",
    re.IGNORECASE,
)
_ACTIVITY_VALUE_RE = re.compile(
    r"(?:<|>|~|=|≤|≥)?\s*\d+(?:\.\d+)?\s*"
    r"(?:nM|μM|uM|mM|pM|M|%|fold|x)\b|"
    r"\+{2,4}|[十]{2,4}|"
    r"\b(?:active|inactive|weak|moderate|strong|ND|NA|NT)\b",
    re.IGNORECASE,
)
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_HEADER_UNIT_RE = re.compile(
    # ``%`` is punctuation, so a leading ``\b`` never matches inside ``(%)`` or
    # ``抑制率 (%)`` — the target-qualified CN headers print the unit exactly there.
    r"%|\b(?:nM|μM|uM|mM|pM|M|fold|x)\b",
    re.IGNORECASE,
)
_QUALITATIVE_CELL_RE = re.compile(
    r"^(?:\+{1,4}|[十]{1,4}|active|inactive|weak|moderate|strong|nd|na|nt|[a-d])$",
    re.IGNORECASE,
)
#: A published "no data" marker. It is a missing value, not an inactivity grade
#: and not a zero; the cell is counted as handled but produces no measurement.
_MISSING_VALUE_RE = re.compile(r"^(?:ND|NA|NT)$", re.IGNORECASE)
#: One printed value expression: a comparator, a number, an optional error term
#: (``± SEM``) and an optional parenthetical percentage. A cell that prints two
#: of them holds two readings the layout merged into one cell, so neither can
#: be attributed to the row without guessing.
_VALUE_EXPRESSION_RE = re.compile(
    r"(?:<=|>=|<|>|=|~|≤|≥|≈)?\s*\d+(?:\.\d+)?"
    r"(?:\s*±\s*\d+(?:\.\d+)?)?"
    r"(?:\s*\(\s*[+-]?\d+(?:\.\d+)?\s*%\s*\))?"
)
# A data row starts with a compound designation. Chemical fragments OCR'd out of
# a structure column (``H3C``, ``N.``), prose, and qualitative symbols are not
# designations, so a value beside them stays unattributed instead of being
# attached to a compound that never owned it.
_DESIGNATION_CODE_RE = re.compile(r"^[A-Za-z]{1,4}\d{2,}[A-Za-z]?$")
_DESIGNATION_CJK_RE = re.compile(r"^(?=.*\d)[\w\u4e00-\u9fff\-–.()（）]{1,32}$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_STANDALONE_VALUE_RE = re.compile(
    r"^(?:<|>|~|=|≤|≥)?\s*[-+]?\d+(?:\.\d+)?\s*"
    r"(?:nM|μM|uM|mM|pM|M|%|fold|x)?\s*$|^[+十]{1,4}$",
    re.IGNORECASE,
)
_LABEL_HEADER_RE = re.compile(
    r"(?:compound|example|molecule|no\b|编号|实施例|化合物|code)", re.IGNORECASE
)
_ASSAY_HEADER_RE = re.compile(r"\b(?:FLIPR|HTRF|IP1|assay)\b|arrestin", re.IGNORECASE)
#: Data rows one refused-table task carries. Two rows per task turned a single
#: document's refused tables into 192 separate gaps — a model turn each — while an
#: answer may return 200 items. Eight rows stay well inside the contract's
#: 4000-character excerpt cap and settle a table in a few tasks.
TABLE_ROWS_PER_GAP = 8

#: A label column whose header states that its rows are *example* numbers. The cell
#: prints the number alone (``实施例编号 | 2``), so the header is the only place the
#: key space can come from.
_EXAMPLE_LABEL_HEADER_RE = re.compile(
    r"(?:example|实施例|実施例|制备例)", re.IGNORECASE
)


@dataclass(frozen=True)
class _HeaderColumn:
    """One flattened header column of a table."""

    index: int
    text: str
    metric: str | None
    unit: str
    target: str | None
    is_label: bool


@dataclass(frozen=True)
class _TableLayout:
    """Flattened view of one activity table.

    Published tables span a metric header across sibling columns and repeat
    ``(label, value)`` column pairs inside a single row. Resolving both here
    keeps the parser and the completeness check from disagreeing about what the
    table declares.
    """

    columns: list[_HeaderColumn]
    data_rows: list[list[str]]
    pairs: list[tuple[int, int]]


def _is_activity_table(table_md: str) -> bool:
    """Return whether a Markdown table contains activity signals.

    A table is eligible when its first rows contain an activity header or any
    value with a recognized activity unit. Layout validation happens separately;
    an ambiguous activity table remains eligible for an evidence-scoped LLM gap.
    """
    rows = [row for row in table_md.split("\n") if row.strip()]
    if len(rows) < 2 or not any(_TABLE_SEPARATOR_RE.match(row) for row in rows[1:3]):
        return False
    sample = _normalize_table_markup("\n".join(rows[:5]))
    return bool(
        _ACTIVITY_HEADER_RE.search(sample) or _ACTIVITY_VALUE_RE.search(table_md)
    )


#: Table families that are never activity tables, whatever else they mention.
#: A reagent list names the target (``MRGPRX2-CHO``) and a synthesis table names
#: ``Compound E098``, so a loose signal probe fires on both; their headers are
#: what settle the question. Incubation-condition tables (``肝微粒体``) state how
#: a sample was handled, not what it measured.
_NON_ACTIVITY_TABLE_RE = re.compile(
    r"(?:试剂|耗材|材料|批号|合成|制备|表征|收率|产率|原料|孵育|微粒体|受试化合物|"
    r"reagents?|materials?|suppliers?|synthes(?:is|ized|es)|prepar(?:ation|ed)|"
    r"characteriz|yields?|incubat|microsom|NADPH|NMR|LCMS|HPLC|MS\b)",
    re.IGNORECASE,
)

#: Value evidence for the *gate*: an unambiguous activity unit, a percentage, or
#: a qualitative bin. Bare ``M`` is excluded — structure fragments OCR to
#: ``0 m``, and that is not a reading.
_GATE_VALUE_RE = re.compile(
    r"(?:<|>|~|=|≤|≥)?\s*\d+(?:\.\d+)?\s*(?:nM|μM|uM|mM|pM|%)\b|"
    r"\+{2,4}|[十]{2,4}|"
    r"\b(?:active|inactive|weak|moderate|strong|ND|NA|NT)\b",
    re.IGNORECASE,
)


def looks_like_activity_table(raw_text: str) -> bool:
    """Return whether raw table evidence is an activity table we failed to read.

    This is the gate for *reporting a refusal*: a table that merely names a
    target or a compound is not a gap. Structural activity evidence — an
    activity header or a value carrying a recognized activity unit — qualifies,
    and a recognized non-activity family settles the other way.
    """
    rows = [row for row in str(raw_text).split("\n") if row.strip()]
    if len(rows) < 2:
        return False
    head = _normalize_table_markup("\n".join(rows[:5]))
    if _NON_ACTIVITY_TABLE_RE.search(head):
        return False
    return bool(
        _ACTIVITY_HEADER_RE.search(head)
        or _GATE_VALUE_RE.search(raw_text)
        or (
            _LABEL_HEADER_RE.search(head)
            and _ASSAY_HEADER_RE.search(head)
            and _NUMERIC_RE.search(raw_text)
        )
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


def _fill_spanned_cells(cells: Sequence[str]) -> list[str]:
    """Carry a spanned header cell into the empty siblings to its right."""
    filled: list[str] = []
    carried = ""
    for cell in cells:
        text = _normalize_table_markup(cell)
        if text:
            carried = text
        filled.append(text or carried)
    return filled


def activity_table_excerpts(table_md: str) -> list[tuple[str, list[str]]]:
    """Keep the printed header bands and a bounded run of data rows per LLM task."""
    lines = [line for line in table_md.splitlines() if line.strip()]
    if not lines or not all(_split_pipe_row(line) for line in lines):
        return [(table_md, [])]
    separator = next(
        (i for i, line in enumerate(lines) if _TABLE_SEPARATOR_RE.match(line)), None
    )
    if separator is None or separator == 0:
        return [(table_md, [])]
    start = separator + 1
    while start < len(lines) and start <= separator + 2:
        if not _is_header_band_row(_split_pipe_row(lines[start])):
            break
        start += 1
    data = lines[start:]
    label_columns = [
        i
        for i, cell in enumerate(_split_pipe_row(lines[0]))
        if _LABEL_HEADER_RE.search(cell)
    ] or [0]
    return [
        (
            "\n".join([*lines[:start], *data[i : i + TABLE_ROWS_PER_GAP]]),
            [
                cells[column]
                for line in data[i : i + TABLE_ROWS_PER_GAP]
                for cells in [_split_pipe_row(line)]
                for column in label_columns
                if column < len(cells) and _is_row_label(cells[column])
            ],
        )
        for i in range(0, len(data), TABLE_ROWS_PER_GAP)
    ] or [(table_md, [])]


def table_cell_matches(
    table_md: str,
    source_quote: str,
    *,
    row_label: str,
    raw_value: str,
    column: int,
) -> bool:
    """Ground a draft in one cell and its own printed designation column."""

    def compact(text: str) -> str:
        return re.sub(r"\s+", "", text)

    lines = [line for line in table_md.splitlines() if line.strip()]
    quoted = [line for line in lines if compact(line) == compact(source_quote)]
    if len(quoted) != 1:
        return False
    cells = _split_pipe_row(quoted[0])
    header_rows = [_split_pipe_row(line) for line in lines[:5]]
    header = next(
        (
            row
            for row in header_rows
            if any(_LABEL_HEADER_RE.search(cell) for cell in row)
        ),
        header_rows[0],
    )
    label_columns = [
        i for i, cell in enumerate(header) if _LABEL_HEADER_RE.search(cell)
    ] or [0]
    label_column = max((i for i in label_columns if i < column), default=-1)
    return (
        0 <= label_column < column < len(cells)
        and _is_row_label(cells[label_column])
        and compact(cells[label_column]) == compact(row_label)
        and compact(cells[column]) == compact(raw_value)
    )


def _clean_target(text: str) -> str | None:
    """Return a header cell's assay target with metric/unit noise removed."""
    target = METRIC_TOKEN_RE.sub(" ", text.replace("拮抗剂", " "))
    target = _HEADER_UNIT_RE.sub(" ", target)
    target = re.sub(r"[()\[\]{}$,:;]", " ", target)
    target = re.sub(
        r"(?i)\b(?:result|results|activity|assay|value|compound|number|antagonist)\b",
        " ",
        target,
    )
    # A footnote marker and the error-term label are not part of the assay name:
    # ``IC50 ± [μM]a (% inhibition ± SEM)c`` names the assay in the rest.
    target = re.sub(r"(?i)\b(?:SEM|SD)\b", " ", target)
    target = target.replace("±", " ")
    target = re.sub(r"(?<![A-Za-z0-9])[a-d](?![A-Za-z0-9])", " ", target)
    cleaned = " ".join(target.split())
    # ``抑制% (300 nM)`` leaves the concentration behind, and a bare number states a
    # condition rather than an assay target.
    if not cleaned or cleaned.isdigit() or cleaned in {"活性", "结果", "数值"}:
        return None
    return cleaned


def _activity_header_columns(
    header_cells: list[str],
) -> list[tuple[int, str, str, str | None]]:
    """Return ``(column, metric, unit, target)`` tuples from a table header."""
    columns: list[tuple[int, str, str, str | None]] = []
    for column, raw_cell in enumerate(_fill_spanned_cells(header_cells)):
        cell = raw_cell
        metrics = find_activity_metrics(cell)
        if not metrics:
            continue
        # A named endpoint beats surrounding words like "antagonist activity".
        metric = next(
            (
                name
                for name in metrics
                if re.fullmatch(r"p?(?:(?:IC|EC|ED|GI|AC|CC)\d+|K[di])", name)
            ),
            metrics[0],
        )
        unit_match = _HEADER_UNIT_RE.search(cell)
        columns.append(
            (
                column,
                metric,
                unit_match.group(0) if unit_match else "",
                _clean_target(cell),
            )
        )
    return columns


def _metric_of_cell(cell: str) -> tuple[str, str, str | None] | None:
    """Return ``(metric, unit, target)`` for one header cell, or ``None``.

    A published table may print the metric in a row other than the one the
    layout treats as the header: a US application prints the assay name in a
    spanning title row and ``IC50 ± [μM]`` in the row below it.
    """
    columns = _activity_header_columns([cell])
    if not columns:
        return None
    _index, metric, unit, target = columns[0]
    return metric, unit, target


def _is_header_band_row(row: Sequence[str]) -> bool:
    """Return whether a row after the separator still belongs to the header."""
    cells = [cell for cell in row if cell.strip()]
    if not cells:
        return False
    return not any(_STANDALONE_VALUE_RE.match(cell.strip()) for cell in cells)


def _read_table_layout(table_md: str) -> _TableLayout | None:
    """Flatten one Markdown table into header columns, pairs and data rows."""
    rows = [_split_pipe_row(line) for line in table_md.splitlines() if line.strip()]
    rows = [row for row in rows if row]
    separator_index = next(
        (
            index
            for index, row in enumerate(rows)
            if _TABLE_SEPARATOR_RE.match("|" + "|".join(row) + "|")
        ),
        None,
    )
    if separator_index is None or separator_index == 0:
        return None

    head_rows = rows[:separator_index]
    rest = rows[separator_index + 1 :]
    # A repeated spanning title is not the column header; require an explicit
    # designation and metric in the next row before promoting it.
    if (
        rest
        and len(set(head_rows[-1])) == 1
        and _is_header_band_row(rest[0])
        and any(_LABEL_HEADER_RE.search(cell) for cell in rest[0])
        and _activity_header_columns(rest[0])
    ):
        head_rows = [rest[0]]
        rest = rest[1:]
    band = 0
    while band < len(rest) and band < 2 and _is_header_band_row(rest[band]):
        band += 1

    designation_columns = [
        i for i, cell in enumerate(head_rows[-1]) if _LABEL_HEADER_RE.search(cell)
    ]
    # A target under the designation header signals lost spans, not a new column.
    if any(
        row[i].strip() and not _LABEL_HEADER_RE.search(row[i])
        for row in rest[:band]
        for i in designation_columns
        if i < len(row)
    ):
        return None

    primary = head_rows[-1]
    #: A metric printed in one header cell spans the empty siblings to its right
    #: (``化合物编号 | IC50(nM) |  |  |``), so the metric is looked up in the
    #: filled header row.
    filled_primary = _fill_spanned_cells(primary)
    band_rows = rest[:band]
    #: Rows printed above the header row: a US table names the assay there and
    #: states the metric in the row below.
    title_rows = head_rows[:-1]

    columns: list[_HeaderColumn] = []
    for index in range(len(primary)):
        band_cells = [row[index] for row in band_rows if index < len(row)]
        title_cells = [row[index] for row in title_rows if index < len(row)]
        metric: str | None = None
        unit = ""
        header_target: str | None = None
        metric_source = "primary"
        for source, cell in (
            ("primary", filled_primary[index] if index < len(filled_primary) else ""),
            *(("band", cell) for cell in band_cells),
            *(("title", cell) for cell in title_cells),
        ):
            found = _metric_of_cell(cell)
            if found is not None:
                metric, unit, header_target = found
                metric_source = source
                break
        label_text = " ".join(
            part.strip() for part in [primary[index], *band_cells] if part.strip()
        )
        text = " ".join(
            part.strip()
            for part in [primary[index], *band_cells, *title_cells]
            if part.strip()
        )
        # The assay name is printed in the spanning title above the metric row;
        # the metric row carries only the endpoint, its unit and its footnotes.
        if metric_source == "primary":
            target = _clean_target(" ".join(band_cells)) or header_target
        else:
            target = (
                _clean_target(" ".join([primary[index], *band_cells])) or header_target
            )
        columns.append(
            _HeaderColumn(
                index=index,
                text=text,
                metric=metric,
                unit=unit,
                target=_clean_target(target) if (metric and target) else None,
                is_label=bool(_LABEL_HEADER_RE.search(label_text)) and metric is None,
            )
        )

    metric_columns = [column for column in columns if column.metric]
    if not metric_columns:
        return None
    label_columns = [column.index for column in columns if column.is_label] or [0]
    pairs = [
        (
            max(
                (index for index in label_columns if index < column.index),
                default=label_columns[0],
            ),
            column.index,
        )
        for column in metric_columns
    ]
    return _TableLayout(
        columns=columns,
        data_rows=[row for row in rest[band:] if row],
        pairs=pairs,
    )


def _is_row_label(value: str) -> bool:
    """Return whether a cell is a compound designation a value can attach to."""
    stripped = value.strip()
    if not stripped or len(stripped) > 32:
        return False
    if _QUALITATIVE_CELL_RE.fullmatch(stripped):
        return False
    # CN120943813A p95 prints a measured positive control without a numeric label.
    if stripped == "阳参化合物":
        return True
    from mbforge.domain.patent import designation_key

    # The pipeline's own designation space first, so one designation is never read
    # two ways: ``实施例 30`` (the corpus prints the space) and ``Example 30`` are
    # row labels here exactly because they are designations everywhere else.
    if designation_key(stripped):
        return True
    if _DESIGNATION_CODE_RE.match(stripped):
        return True
    return bool(_DESIGNATION_CJK_RE.match(stripped) and _CJK_RE.search(stripped))


def _cell_value_count(cell: str) -> int:
    """Return how many independent value expressions a cell prints.

    ``11.6 ± 3.7`` is one reading with its error term; ``>100 (4%)`` is one
    censored reading with its inhibition; ``>100 (40%) >100 (45%)`` is two
    readings the layout merged into one cell, and neither of them can be
    attributed to the row without guessing.
    """
    text = _normalize_table_markup(cell).strip()
    if not text or _MISSING_VALUE_RE.fullmatch(text):
        return 0
    if _QUALITATIVE_CELL_RE.fullmatch(text):
        return 1
    return len(_VALUE_EXPRESSION_RE.findall(text))


def _normalize_bin_symbol(value: str) -> str:
    """Map the OCR substitution ``十`` back to the ``+`` bin symbol."""
    stripped = value.strip()
    return "+" * len(stripped) if re.fullmatch(r"[十]{1,4}", stripped) else value


def _cell_has_activity_value(cell: str) -> bool:
    """Return whether a table cell carries a quantitative/qualitative value."""
    stripped = _normalize_table_markup(cell).strip()
    if _MISSING_VALUE_RE.fullmatch(stripped):
        return False
    return bool(
        _NUMERIC_RE.search(stripped) or _QUALITATIVE_CELL_RE.fullmatch(stripped)
    )


@dataclass(frozen=True)
class _CellCoverage:
    """How one table's value cells divide up.

    ``expected`` counts the cells that name a compound and print exactly one
    value: those are the readings a reader can attribute. The other three
    counts are the cells that cannot become one, each for its own reason, so a
    table that publishes part of itself says which part it left out.
    """

    expected: int
    no_designation: int
    ambiguous_value: int
    unreadable: int


def _classify_cells(table_md: str) -> _CellCoverage:
    """Sort one table's value cells into the readings it can and cannot yield."""
    layout = _read_table_layout(table_md)
    if layout is None:
        return _CellCoverage(0, 0, 0, 0)
    expected = no_designation = ambiguous_value = unreadable = 0
    for row in layout.data_rows:
        for label_column, value_column in layout.pairs:
            if value_column >= len(row):
                continue
            cell = _normalize_table_markup(row[value_column]).strip()
            if not cell or _MISSING_VALUE_RE.fullmatch(cell):
                continue
            label = row[label_column].strip() if label_column < len(row) else ""
            if not _is_row_label(label):
                # The value names no compound, so it is not a reading yet.
                no_designation += 1
                continue
            if _cell_value_count(cell) > 1:
                ambiguous_value += 1
                continue
            if not _cell_has_activity_value(cell):
                unreadable += 1
                continue
            expected += 1
    return _CellCoverage(
        expected=expected,
        no_designation=no_designation,
        ambiguous_value=ambiguous_value,
        unreadable=unreadable,
    )


def _parse_simple_activity_table(
    table_md: str,
    table_idx: int,
    page_num: int | None,
    *,
    default_target: str | None = None,
    legend: Mapping[str, str] | None = None,
) -> list[ActivityRecord]:
    """Parse a structurally simple activity table without an LLM.

    The parser requires a Markdown separator, an activity metric header, and a
    compound designation beside every value it reports. Numeric values,
    comparison operators, and qualitative tokens go through the same
    normalization contract as LLM results. A cell that cannot be attributed
    stays unparsed, so the caller skips the table instead of guessing.
    """
    # Lazy import to break the parsing ↔ extraction cycle.
    # ``_build_activity_record`` lives with the LLM-orchestration path but
    # the simple-table parser produces the same record shape, so we import
    # it on first call rather than at module load.
    from mbforge.service.pipeline.activity.extraction import _build_activity_record

    layout = _read_table_layout(table_md)
    if layout is None:
        return []
    metrics = {column.index: column for column in layout.columns if column.metric}
    resolved_legend = dict(extract_qualitative_legend(table_md))
    if legend:
        resolved_legend.update(legend)

    records: list[ActivityRecord] = []
    for row_idx, row in enumerate(layout.data_rows):
        for label_column, value_column in layout.pairs:
            if value_column >= len(row):
                continue
            value_text = _normalize_bin_symbol(row[value_column])
            if not _cell_has_activity_value(value_text):
                continue
            if _cell_value_count(value_text) > 1:
                # Two readings merged into one cell: which of them belongs to
                # this row is not printed, so the cell stays unread.
                continue
            # A blank Markdown cell cannot prove a span; OCR may have lost a label.
            label = row[label_column].strip() if label_column < len(row) else ""
            if not _is_row_label(label):
                continue
            column = metrics[value_column]
            target = column.target or default_target
            label_header = (
                layout.columns[label_column].text
                if label_column < len(layout.columns)
                else ""
            )
            record = _build_activity_record(
                {
                    "metric": column.metric,
                    "value": value_text,
                    "value_text": value_text,
                    "unit": column.unit,
                    "operator": "=",
                    "target": target,
                    "raw_text": f"{label}: {column.text} = {value_text}",
                    "confidence": 0.98,
                    "row_label": label,
                    # The column header names the space its row labels are printed in:
                    # ``实施例编号 | 2`` is Example 2 (``@example:2``), not the compound
                    # ``2``. They are different designations throughout this pipeline,
                    # so the header has to decide.
                    "label_space": (
                        "example"
                        if _EXAMPLE_LABEL_HEADER_RE.search(label_header)
                        else "compound"
                    ),
                },
                table_idx=table_idx,
                page_num=page_num,
                header_metric=column.metric,
                legend=resolved_legend,
                default_target=target,
            )
            record.col_idx = value_column
            # The cell's own coordinates: a reading that cannot point at its row
            # and column is not citable, and re-reading the evidence row later
            # cannot recover which cell the number came from.
            record.row_idx = row_idx
            records.append(record)
    return records


def _simple_activity_table_is_complete(
    table_md: str, records: list[ActivityRecord]
) -> bool:
    """Return whether every declared activity cell was parsed deterministically.

    A cell that names a compound and prints one value is expected to become a
    record: a cell that holds something the parser cannot read leaves
    ``expected`` above ``records`` so the caller skips the table instead of
    publishing part of it. A cell that names no compound, or that holds two
    readings merged into one, is not expected to become anything: it is counted
    and reported by :func:`_table_cell_gaps` instead of withholding the rows
    that were read.
    """
    coverage = _classify_cells(table_md)
    return (
        coverage.expected > 0
        and coverage.expected == len(records)
        and coverage.unreadable == 0
    )


def _table_cell_gaps(table_md: str) -> dict[str, int]:
    """Return the cells a table leaves out, by the reason they were left out."""
    coverage = _classify_cells(table_md)
    return {
        "no_designation": coverage.no_designation,
        "ambiguous_value": coverage.ambiguous_value,
    }

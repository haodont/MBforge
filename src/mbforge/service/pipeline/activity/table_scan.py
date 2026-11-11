"""Read one table evidence row into activity readings, or into a reported refusal.

One unit of policy lives here: whether a table's Markdown is an activity table,
whether it is complete, whether it is the page-split tail of the preceding one,
and what a refusal has to say so that it cannot be silent. The evidence loop in
``extraction`` keeps only ordering, the qualitative legend, the prose runs and
the measurement projection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mbforge.service.pipeline.activity.parsing.tables import (
    _TABLE_SEPARATOR_RE,
    _is_activity_table,
    _is_header_band_row,
    _is_row_label,
    _parse_simple_activity_table,
    _simple_activity_table_is_complete,
    _split_pipe_row,
    _table_cell_gaps,
    looks_like_activity_table,
)
from mbforge.service.pipeline.layout.table_html import (
    html_table_to_markdown as _html_table_to_markdown,
)

if TYPE_CHECKING:
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.service.pipeline.activity.parsing.tables import ActivityRecord

#: The last activity table read from its own header: (page, evidence id, Markdown).
PreviousTable = tuple[int | None, str, str]


@dataclass(frozen=True)
class TableScan:
    """What one table evidence row yielded.

    A scan can carry readings *and* an informational issue: readings inherited
    across a page break are published, with the inheritance itself reported.
    ``refusal_code`` asks the caller to append one issue and nothing else.
    ``gap_counts`` names the cells the table could not turn into readings, so a
    table that publishes part of itself says which part it left out.
    """

    records: list[ActivityRecord] = field(default_factory=list)
    last_activity: PreviousTable | None = None
    refusal_code: str | None = None
    refusal_message: str = ""
    refusal_ids: tuple[str, ...] = ()
    refusal_severity: str = "warning"
    gap_counts: dict[str, int] = field(default_factory=dict)


def table_markdown(raw_text: str) -> str | None:
    """Return the table's Markdown, or ``None`` when the row holds no table."""
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


def _may_inherit(page: int | None, previous: PreviousTable | None) -> bool:
    """Only the adjacent page may claim the previous table's header."""
    if previous is None or page is None or previous[0] is None:
        return False
    return 0 <= page - previous[0] <= 1


def scan_table_evidence(
    item: SourceEvidence,
    *,
    table_idx: int,
    previous: PreviousTable | None,
    legend: Mapping[str, str] | None = None,
) -> TableScan:
    """Read one ``table`` evidence row.

    A table with its own metric header is parsed directly. A row the layout pass
    split across a page break keeps its columns and loses its header; its header
    is borrowed from the previous activity table, from the adjacent page only,
    and the borrowed metric is reported. Everything else that looks like an
    activity table is refused out loud rather than skipped.
    """
    table_text = table_markdown(item.raw_text)
    if table_text is None:
        if looks_like_activity_table(item.raw_text):
            return TableScan(
                refusal_code="unsupported_table_format",
                refusal_message="activity table format is not supported",
                refusal_ids=(item.evidence_id,),
            )
        return TableScan()

    records = _parse_simple_activity_table(
        table_text,
        table_idx=table_idx,
        page_num=item.page,
        legend=legend,
    )
    if records and not _is_activity_table(table_text):
        records = []
    if records and not _simple_activity_table_is_complete(table_text, records):
        return TableScan(
            refusal_code="complex_activity_table",
            refusal_message="activity table contains unparsed cells",
            refusal_ids=(item.evidence_id,),
        )
    if records:
        return TableScan(
            records=records,
            last_activity=(item.page, item.evidence_id, table_text),
            gap_counts=_table_cell_gaps(table_text),
        )

    if _may_inherit(item.page, previous) and previous is not None:
        inherited_ids = (previous[1], item.evidence_id)
        continued = parse_continuation(
            previous[2],
            table_text,
            table_idx=table_idx,
            page_num=item.page,
            legend=legend,
        )
        if continued:
            # Published under a header this row does not print: a documented
            # continuation, but it must stay citable rather than silent.
            return TableScan(
                records=continued,
                refusal_code="table_header_inherited",
                refusal_message=(
                    "activity table continues from the previous page without its "
                    "header; the previous table's header was used"
                ),
                refusal_ids=inherited_ids,
                refusal_severity="info",
            )
        if continued is not None and not looks_like_activity_table(item.raw_text):
            return TableScan(
                refusal_code="complex_activity_table",
                refusal_message=(
                    "activity table continuation could not be read under the "
                    "previous page's header"
                ),
                refusal_ids=inherited_ids,
            )

    if looks_like_activity_table(item.raw_text):
        return TableScan(
            refusal_code="complex_activity_table",
            refusal_message="activity table is incomplete or ambiguous",
            refusal_ids=(item.evidence_id,),
        )
    return TableScan()


def parse_continuation(
    previous_table_md: str,
    continuation_md: str,
    *,
    table_idx: int,
    page_num: int | None,
    legend: Mapping[str, str] | None = None,
) -> list[ActivityRecord] | None:
    """Read the page-split tail of the immediately preceding activity table.

    A table that continues on the next page keeps its columns but loses its
    header row, and the layout pass still emits a separator for the fragment it
    saw (the first printed row becomes a pseudo-header).

    ``None`` means the fragment is not a continuation at all - it prints its own
    header, or its first cell is no designation - so the caller treats it as an
    ordinary table. An empty list means it did look like a continuation and did
    not parse completely, which is a refusal the caller has to report.
    """
    previous_lines = [
        line for line in str(previous_table_md).splitlines() if line.strip()
    ]
    continuation_lines = [
        line for line in str(continuation_md).splitlines() if line.strip()
    ]
    separator = next(
        (
            index
            for index, line in enumerate(previous_lines)
            if _TABLE_SEPARATOR_RE.match(line)
        ),
        None,
    )
    if separator is None or separator == 0 or not continuation_lines:
        return None
    header_cells = _split_pipe_row(previous_lines[separator - 1])
    body = [line for line in continuation_lines if not _TABLE_SEPARATOR_RE.match(line)]
    first_cells = _split_pipe_row(body[0]) if body else []
    if not header_cells or not first_cells:
        return None
    if len(first_cells) != len(header_cells):
        return None
    # A fragment that prints its own header band - units, a label header, no
    # designation in the first cell - is a different table on the same page, not
    # a tail. Borrowing the previous metric over it would invent readings.
    if _is_header_band_row(first_cells) or not _is_row_label(first_cells[0]):
        return None
    combined = "\n".join([*previous_lines[: separator + 1], *body])
    records = _parse_simple_activity_table(
        combined, table_idx=table_idx, page_num=page_num, legend=legend
    )
    if not records or not _simple_activity_table_is_complete(combined, records):
        return []
    return records


__all__ = ["TableScan", "parse_continuation", "scan_table_evidence", "table_markdown"]

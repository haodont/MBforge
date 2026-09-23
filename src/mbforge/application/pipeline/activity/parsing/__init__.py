"""Table-parsing subpackage for activity extraction.

Re-exports the deterministic table-parsing primitives that used to live in
:mod:`mbforge.application.pipeline.activity.extraction` so existing call sites can keep
importing them from the old path while new code targets
``mbforge.application.pipeline.activity.parsing`` directly.
"""

from __future__ import annotations

from mbforge.application.pipeline.activity.parsing.tables import (
    _NUMERIC_RE,
    _activity_header_columns,
    _cell_has_activity_value,
    _is_activity_table,
    _normalize_table_markup,
    _parse_simple_activity_table,
    _simple_activity_table_is_complete,
    _split_pipe_row,
)
from mbforge.application.pipeline.layout.table_html import (
    html_table_to_markdown as _html_table_to_markdown,
)

__all__ = [
    "_NUMERIC_RE",
    "_activity_header_columns",
    "_cell_has_activity_value",
    "_html_table_to_markdown",
    "_is_activity_table",
    "_normalize_table_markup",
    "_parse_simple_activity_table",
    "_simple_activity_table_is_complete",
    "_split_pipe_row",
]

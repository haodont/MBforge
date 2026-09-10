"""Table-parsing subpackage for activity extraction.

Re-exports the deterministic table-parsing primitives that used to live in
:mod:`mbforge.pipeline.activity.extraction` so existing call sites can keep
importing them from the old path while new code targets
``mbforge.pipeline.activity.parsing`` directly.
"""

from __future__ import annotations

from .tables import (
    _NUMERIC_RE,
    _activity_header_columns,
    _cell_has_activity_value,
    _html_table_to_markdown,
    _HtmlTableParser,
    _is_activity_table,
    _normalize_table_markup,
    _parse_simple_activity_table,
    _simple_activity_table_is_complete,
    _split_pipe_row,
)

__all__ = [
    "_HtmlTableParser",
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

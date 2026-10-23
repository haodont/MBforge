"""Contract tests for the shared HTML-table → Markdown conversion.

The converter is the single normalization point for table-recognition output
(PaddleOCR cloud and SLANet-1M); the activity parser consumes its result, so
the conversion shape is a public cross-module contract.
"""

from __future__ import annotations

from mbforge.service.pipeline.layout.table_html import html_table_to_markdown

# (html, expected markdown) — a padded pipe table is the only accepted shape.
_TABLE_CASES = [
    (
        "<table><tr><th>Compound</th><th>IC50 (nM)</th></tr>"
        "<tr><td>1a</td><td>12.5</td></tr></table>",
        "| Compound | IC50 (nM) |\n| --- | --- |\n| 1a | 12.5 |",
    ),
    (
        "<table><tr><th>A</th><th>B</th><th>C</th></tr><tr><td>x|y</td></tr></table>",
        "| A | B | C |\n| --- | --- | --- |\n| x\\|y |  |  |",
    ),
]

# No usable rows: the converter must yield None rather than raise.
_EMPTY_CASES = ["", "<table>broken", "<table></table>"]


def test_html_table_to_markdown_converts_pads_and_rejects_empty() -> None:
    """Well-formed tables become Markdown; empty/malformed input yields None."""
    for html, expected in _TABLE_CASES:
        assert html_table_to_markdown(html) == expected, html

    for html in _EMPTY_CASES:
        assert html_table_to_markdown(html) is None, html

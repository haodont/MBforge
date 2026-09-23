"""Contract tests for the shared HTML-table → Markdown conversion.

The converter is the single normalization point for table-recognition output
(PaddleOCR cloud and SLANet-1M); the activity parser consumes its result, so
the conversion shape is a public cross-module contract.
"""

from __future__ import annotations

from mbforge.application.pipeline.layout.table_html import html_table_to_markdown


def test_html_table_to_markdown_converts_fragment() -> None:
    """A well-formed HTML table becomes a padded Markdown pipe table."""
    html = (
        "<table><tr><th>Compound</th><th>IC50 (nM)</th></tr>"
        "<tr><td>1a</td><td>12.5</td></tr></table>"
    )
    markdown = html_table_to_markdown(html)
    assert markdown == ("| Compound | IC50 (nM) |\n| --- | --- |\n| 1a | 12.5 |")


def test_html_table_to_markdown_escapes_pipes_and_pads_rows() -> None:
    """Cell ``|`` is escaped and short rows are padded to the table width."""
    html = "<table><tr><th>A</th><th>B</th><th>C</th></tr><tr><td>x|y</td></tr></table>"
    markdown = html_table_to_markdown(html)
    assert markdown == ("| A | B | C |\n| --- | --- | --- |\n| x\\|y |  |  |")


def test_html_table_to_markdown_returns_none_for_empty_or_malformed() -> None:
    """No usable rows (empty or malformed input) yields None, never raises."""
    assert html_table_to_markdown("") is None
    assert html_table_to_markdown("<table>broken") is None
    assert html_table_to_markdown("<table></table>") is None

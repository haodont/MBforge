"""HTML table fragment → Markdown pipe table (shared by layout and activity).

VLM and table-structure backends (PaddleOCR, SLANet-1M) emit HTML tables
for scanned documents; the activity parser and the Hiro-Layout table
recognition both normalize them to Markdown pipe tables. This module owns
that single conversion so neither side re-implements it.
"""

from __future__ import annotations

from html.parser import HTMLParser


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


def html_table_to_markdown(html_text: str) -> str | None:
    """Convert one ``<table>`` fragment to a Markdown pipe table.

    Returns ``None`` when no usable rows are found; malformed HTML is simply
    skipped (the caller treats it as "no table content").
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


__all__ = ["html_table_to_markdown"]

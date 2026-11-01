"""HTML table fragment → Markdown pipe table (shared by layout and activity).

VLM and table-structure backends (PaddleOCR, SLANet-1M) emit HTML tables
for scanned documents; the activity parser and the Hiro-Layout table
recognition both normalize them to Markdown pipe tables. This module owns
that single conversion so neither side re-implements it.
"""

from __future__ import annotations

from html.parser import HTMLParser


class _HtmlTableParser(HTMLParser):
    """Expand explicit HTML spans into logical columns; never infer blank spans."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: dict[int, str] | None = None
        self._cell: list[str] | None = None
        self._spans: dict[int, tuple[int, str]] = {}
        self._column = 0
        self._rowspan = self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = {column: text for column, (_, text) in self._spans.items()}
            self._spans = {
                column: (remaining - 1, text)
                for column, (remaining, text) in self._spans.items()
                if remaining > 1
            }
            self._column = 0
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            attributes = dict(attrs)
            self._rowspan = int(attributes.get("rowspan") or "1")
            self._colspan = int(attributes.get("colspan") or "1")
            # Bound expansion of malformed or untrusted model output.
            if not (1 <= self._rowspan <= 1000 and 1 <= self._colspan <= 1000):
                raise ValueError("unsupported table span")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell).split()).replace("|", "\\|")
            while self._column in self._row:
                self._column += 1
            for column in range(self._column, self._column + self._colspan):
                if column in self._row:
                    raise ValueError("overlapping table spans")
                self._row[column] = text
                if self._rowspan > 1:
                    self._spans[column] = (self._rowspan - 1, text)
            self._column += self._colspan
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(
                    [self._row.get(column, "") for column in range(max(self._row) + 1)]
                )
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def html_table_to_markdown(html_text: str) -> str | None:
    """Convert one ``<table>`` fragment to a Markdown pipe table.

    Returns ``None`` for empty or unsupported/malformed tables. Callers must
    retain the source HTML for review instead of guessing a repaired grid.
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

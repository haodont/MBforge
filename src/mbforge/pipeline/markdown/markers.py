"""Shared regex markers for the markdown pipeline stage.

Page markers, E-SMILES code blocks, headings, and Markush context signals
used across markdown-stage modules and the persist stage.
"""

from __future__ import annotations

import re

_PAGE_MARKER_RE = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")
_ESMILES_BLOCK_RE = re.compile(r"```esmiles\n(.*?)\n```", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def collect_page_boundaries(md_text: str) -> list[tuple[int, int]]:
    """Return ordered ``(page_num, line_index)`` for every ``<!-- PAGE N -->`` marker.

    Shared page-attribution helper: callers index boundaries by line to
    map any markdown offset (table row, example heading) to the page it
    lives on.
    """
    boundaries: list[tuple[int, int]] = []
    for lineno, line in enumerate(md_text.split("\n")):
        match = _PAGE_MARKER_RE.match(line.strip())
        if match:
            boundaries.append((int(match.group(1)), lineno))
    return boundaries


_MARKUSH_CONTEXT_RE = re.compile(
    r"\bmarkush\b"
    r"|\b(?:general|generic)\s+(?:formula|structure)\b"
    r"|\bformula\s+[ivxlcdm]+\b"
    r"|\boptionally\s+substituted\b"
    r"|\b(?:variable|unresolved)\s+(?:group|moiety|substituent)s?\b"
    r"|\b(?:R|A|X|W)\s*[0-9₀-₉]+\b"
    r"|\bR\s*group(?:s)?\b",
    re.IGNORECASE,
)

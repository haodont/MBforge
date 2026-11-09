"""Shared regex markers for the markdown pipeline stage.

Page markers, E-SMILES code blocks, headings, and Markush context signals
used across the Markdown stage and the Patent facts parser.
"""

from __future__ import annotations

import re

_PAGE_MARKER_RE = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")
_ESMILES_BLOCK_RE = re.compile(r"```esmiles\n(.*?)\n```", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


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

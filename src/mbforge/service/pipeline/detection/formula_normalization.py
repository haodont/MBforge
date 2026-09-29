"""Deterministic cleanup for malformed patent LaTeX emitted by OCR/LLMs.

Normalizes common chemistry formula mutations without changing prose.
"""

from __future__ import annotations

import re

_BARE_ATOM = re.compile(
    r"\\(?:mathrm|mathbb)\{(?:[^{}]|\{[^{}]*\})+\}(?:\^\{[^{}]*\}|\^\w+)?"
)


def normalize_patent_formulas(text: str) -> str:
    """Normalize common chemistry formula mutations without changing prose."""
    normalized = text.replace("\\\\mathrm", "\\mathrm").replace(
        "\\\\mathbb", "\\mathbb"
    )
    parts = normalized.split("$")
    normalized = "$".join(
        part if index % 2 else _BARE_ATOM.sub(r"$\g<0>$", part)
        for index, part in enumerate(parts)
    )

    def clean_formula(match: re.Match[str]) -> str:
        token = match.group(0)
        display = token.startswith("$$")
        body = token[2 if display else 1 : -2 if display else -1]
        body = re.sub(
            r"\\mathrm\{([A-Za-z]+)\*?\{\s*([^{}]+?)\s*\}\}", r"\\mathrm{\1}_{\2}", body
        )
        body = re.sub(
            r"\\mathrm\{([A-Za-z]+)\}\{\s*([^{}]+?)\s*\}", r"\\mathrm{\1}_{\2}", body
        )
        body = re.sub(r"(?<=\))\s*\*\s*(?=\d)", "", body)
        body = re.sub(r"\s*([−–])\s*", "-", body)
        return ("$$" if display else "$") + body.strip() + ("$$" if display else "$")

    return re.sub(r"\$\$[\s\S]+?\$\$|\$[^$\n]+?\$", clean_formula, normalized)


def clean_markdown_file(path: str) -> bool:
    """Normalize a Markdown artifact in place; return whether it changed."""
    from pathlib import Path

    target = Path(path)
    original = target.read_text(encoding="utf-8")
    cleaned = normalize_patent_formulas(original)
    if cleaned == original:
        return False
    target.write_text(cleaned, encoding="utf-8")
    return True

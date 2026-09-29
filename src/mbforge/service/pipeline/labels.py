"""Shared compound-label extraction primitives.

Explicit compound-label mentions (``化合物4A`` / ``compound 28`` /
``实施例21-a``) are used by the Patent section parser and the later text-link
pass. The helpers live in this neutral module so downstream stages do not
import from PatentStage.
"""

from __future__ import annotations

import re

_EXPLICIT_COMPOUND_LABEL_RE = re.compile(
    r"(?:(?:compound|example|molecule)\s*(?:no\.?\s*)?|"
    r"(?:化合物|实施例)\s*)([0-9]+[A-Za-z]?(?:-[A-Za-z])?)",
    re.IGNORECASE,
)


def _label_token(name: str) -> str:
    """Return the bare compound token used for distant context lookup."""
    return re.sub(
        r"^(?:compound|example|molecule|化合物|实施例)\s*",
        "",
        name.strip(),
        flags=re.IGNORECASE,
    ).strip()


def _explicit_compound_labels(text: str) -> list[str]:
    """Return unique explicit compound labels from prose outside ESMILES."""
    labels: list[str] = []
    for match in _EXPLICIT_COMPOUND_LABEL_RE.finditer(text):
        label = match.group(1).strip()
        if label and label not in labels:
            labels.append(label)
    return labels

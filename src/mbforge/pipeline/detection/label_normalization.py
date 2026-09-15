"""Deterministic normalization for coreference labels.

The OCR / coref / caption extractors upstream emit labels in many shapes:

- ``"R₁"``, ``"R1"``, ``"R 2"`` — numbered R-groups (subscripts stripped).
- ``"Formula I"``, ``"formula ii"``, ``"FORMULA IV"`` — formula designations.
- ``"A1"``, ``"A₂"`` — A-labelled rings / attachment fragments.
- ``"3a"``, ``"12b"`` — compound / example numbering.

This module collapses them into a single canonical form so the
persistence layer can index, dedup, and review them deterministically:

- ``raw_coref_label`` — the original string, untouched.
- ``normalized_label`` — canonical form (whitespace collapsed, subscript
  digits folded to ASCII, formula letters uppercased).
- ``label_kind`` — one of ``formula`` / ``r_group`` / ``ring`` /
  ``compound`` / ``example`` / ``unknown``.

The classifier and persistence layer read these three fields directly;
the legacy ``formula_label`` / ``label`` keys on
``Molecule.properties`` is still written for back-compat but
are no longer the source of truth.

Why deterministic (no LLM): chemistry labels follow a tiny grammar; a
handful of regexes cover every variant observed in the corpus.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

from mbforge.core.patent import compound_label_key


class LabelKind(str, Enum):  # noqa: UP042 — matches existing Enum-string pattern in mbforge.models.agent
    """Stable kind taxonomy for coreference labels."""

    FORMULA = "formula"
    R_GROUP = "r_group"
    RING = "ring"
    COMPOUND = "compound"
    EXAMPLE = "example"
    UNKNOWN = "unknown"


LABEL_KINDS: frozenset[LabelKind] = frozenset(LabelKind)


_SUBSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

# Roman numerals, lowercase or uppercase, with optional leading/trailing
# whitespace. The classifier emits these in OCR text as "Formula  II"
# (extra spaces) and "formula iii" (lower-case); we canonicalise both.
_ROMAN_PATTERN = re.compile(r"^formula\s+([IVX]+)$", re.IGNORECASE)

# R-group labels: literal "R" (uppercase only — lowercase "r" is too
# noisy inside chemistry prose), optionally followed by a Unicode
# subscript, ASCII digit, or a small gap.
_R_GROUP_PATTERN = re.compile(r"^R\s*([0-9]+|[₀-₉]+)$")

# A-labelled rings/attachment fragments. The leading letter is fixed to
# "A" to avoid swallowing generic prose.
_RING_PATTERN = re.compile(r"^A\s*([0-9]+|[₀-₉]+)$")

# Explicit "Example N" labels from text extraction.
_EXAMPLE_PATTERN = re.compile(r"^example\s+([0-9]+)$", re.IGNORECASE)


def _strip_subscripts(value: str) -> str:
    """Fold Unicode subscript digits to their ASCII counterparts."""
    return value.translate(_SUBSCRIPT_DIGITS)


def _collapse_whitespace(value: str) -> str:
    """Collapse internal whitespace runs to a single space and trim."""
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class NormalizedLabel:
    """Result of normalizing a raw coreference label.

    Attributes:
        raw: The original string, preserved verbatim for traceability.
        normalized: Canonical form used for indexing, dedup, and review.
        kind: One of the :class:`LabelKind` values. ``UNKNOWN`` is
            represented by the absence of a result, not by setting this
            field, so callers cannot accidentally treat garbage as data.
    """

    raw: str
    normalized: str
    kind: LabelKind


def normalize_coref_label(raw: str) -> NormalizedLabel | None:
    """Return a :class:`NormalizedLabel` for *raw*, or ``None`` if it is
    not a recognizable label.

    The returned object always carries the verbatim ``raw`` value so the
    caller can audit what was originally seen; ``normalized`` is the
    canonical form and ``kind`` classifies the label for downstream
    pipelines.
    """
    if not raw:
        return None
    collapsed = _collapse_whitespace(raw)
    if not collapsed:
        return None

    formula = _ROMAN_PATTERN.match(collapsed)
    if formula:
        roman = formula.group(1).upper()
        return NormalizedLabel(
            raw=raw,
            normalized=f"Formula {roman}",
            kind=LabelKind.FORMULA,
        )

    r_group = _R_GROUP_PATTERN.match(collapsed)
    if r_group:
        digits = _strip_subscripts(r_group.group(1))
        return NormalizedLabel(
            raw=raw,
            normalized=f"R{digits}",
            kind=LabelKind.R_GROUP,
        )

    ring = _RING_PATTERN.match(collapsed)
    if ring:
        digits = _strip_subscripts(ring.group(1))
        return NormalizedLabel(
            raw=raw,
            normalized=f"A{digits}",
            kind=LabelKind.RING,
        )

    compound = compound_label_key(collapsed)
    if compound is not None:
        return NormalizedLabel(
            raw=raw,
            normalized=compound,
            kind=LabelKind.COMPOUND,
        )

    example = _EXAMPLE_PATTERN.match(collapsed)
    if example:
        return NormalizedLabel(
            raw=raw,
            normalized=f"Example {example.group(1)}",
            kind=LabelKind.EXAMPLE,
        )

    return None


__all__ = [
    "LABEL_KINDS",
    "LabelKind",
    "NormalizedLabel",
    "normalize_coref_label",
]


# Re-export the canonical ``unicodedata`` normalisation name even though
# we don't currently use NFKC; downstream callers may want to apply it
# to the raw value before passing it in.
_ = unicodedata  # silence "imported but unused" in IDEs

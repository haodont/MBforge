"""Repair the OCR substitutions a scanned patent reliably produces.

Page text comes from RapidOCR on a page render, and a chemistry patent defeats it
in a small, repeatable set of ways. Measured over the 13-document corpus (10,592
text evidence rows):

===========  ======  ==================================================
corruption   count   what it is
===========  ======  ==================================================
``mmo1``     1253    ``mmol`` — the unit's final ``l`` read as ``1``
``[M+H]†``   573     ``[M+H]+`` — superscript ``+`` read as a dagger
``mo1``      84      ``mol``
===========  ======  ==================================================

The pattern is contextual rather than random: the *same* glyph is read correctly
in ``mL`` 2060 times and wrongly only twice, while in ``mmol`` it is wrong 61% of
the time (1253 vs 797). That is a rendering/segmentation artifact, so a
substitution table repairs it exactly — no model is needed for this class.

What this module canNOT do, and must not pretend to: repair a misread *digit*
(``248.0`` that should be ``246.0``), a wrong character inside a chemical name
(``三氯甲基`` for ``三氟甲基``), or an unexpected glyph that is not in the table. Those
need the original pixels and are deliberately left for a later stage.
"""

from __future__ import annotations

import re
from typing import Final

#: Unit and qualifier tokens whose final lowercase ``l`` is routinely read as
#: ``1`` or ``I``. Two forms occur in the corpus: a quantity before the unit
#: (``3.57mmo1``) and a bare unit followed by punctuation or a denominator
#: (``mo1/L``, ``mo1%``). Both are covered; the substitution can never touch a
#: chemical formula or a CAS-style identifier because the stem must be a unit.
_QUANTITY_UNIT = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)"
    r"\s*"
    r"(?P<unit>mmo[1lI]|mo[1lI]|[uμ]mo[1lI]|nmo[1lI])"
    r"(?![A-Za-z0-9])"
)
#: The bare form: ``mo1/L`` (a concentration denominator), ``mo1%``, or a unit at
#: a word boundary. The lookahead accepts a denominator or punctuation so a
#: quantity that already carries its own number (``2mo1/L``) is still covered,
#: while a longer word (``emo1`` in a garbled name) is left untouched.
#:
#: The unit may also arrive split by spurious spaces: a Japanese-font page is
#: rendered with tracking that makes RapidOCR emit ``m mo1`` / ``m mo 1`` for
#: ``mmol``. The space-tolerant form is matched first so the split token is
#: repaired as one unit instead of being rewritten piecemeal.
_SPACED_UNIT = re.compile(
    r"(?<![A-Za-z\u4e00-\u9fff])"
    r"(?P<unit>[uμ]\s*[mn]?\s*m\s*o\s*[1lI]|[mn]?\s*m\s*m\s*o\s*[1lI])"
    r"(?=[/%]|\s*[/%\s）)，。,;；:：]|$)"
)
_BARE_UNIT = re.compile(
    r"(?<![A-Za-z\u4e00-\u9fff])"
    r"(?P<unit>mmo[1lI]|mo[1lI]|[uμ]mo[1lI]|nmo[1lI])"
    r"(?=[/%]|\s*[/%\s）)，。,;；:：]|$)"
)
#: Canonical spelling keyed by the token with its ambiguous final glyph removed.
_UNIT_CANON = {
    "mmo": "mmol",
    "mo": "mol",
    "μmo": "μmol",
    "umo": "μmol",
    "nmo": "nmol",
}

#: ``[M+H]†`` / ``[M+H]‡`` / ``[M+H]⁺``: the adduct's superscript plus is read as a
#: dagger or a modifier letter. Normalised so downstream mass parsing sees ``+``.
_ADDUCT_PLUS = re.compile(r"(\[\s*M\s*[+\-−]\s*[A-Za-z0-9]*\s*\])\s*[†‡⁺⁺]")

#: A hyphen inside a locant already uses several dashes depending on the font.
#: Downstream name parsing expects one form, so unify the family.
_DASH_FAMILY = re.compile(r"[‐‑‒–—―−]")

#: ``ICs0`` / ``ρIC50``: the ``IC`` half-width glyph pair. Only the digit ``0`` for
#: ``O`` substitution is repaired; a genuinely different metric is left alone.
_IC50_GLYPH = re.compile(r"(?<![A-Za-z])(?:ρ\s*)?IC[sS][0O0](?!\d)")

#: Homoglyphs inside Chinese chemical vocabulary. ``已``/``己``/``巳`` are the same
#: hanzi skeleton and the corpus confirms the confusion is systematic, not random:
#: 78 occurrences of ``环已基`` against 105 of the correct ``环己基``, and 33 of
#: ``已烷`` against 20 of ``己烷``.
#:
#: This matters more than a typo usually would: a chemical name that says ``已`` is
#: an unknown character to the name parser, so the whole name fails to parse and the
#: structure behind it is lost. Measured on CN120329282A, all 23 example headings
#: print a full systematic name AND a compound number, and 0 of 23 could be turned
#: into a structure — ``环已基`` alone accounted for the majority.
_CHEM_HOMOGLYPHS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Ring/chain stems: the correct form is 己 (ji), not 已 (yi) or 巳 (si).
    (re.compile(r"环已基"), "环己基"),
    (re.compile(r"环巳基"), "环己基"),
    (re.compile(r"已烷"), "己烷"),
    (re.compile(r"巳烷"), "己烷"),
    (re.compile(r"环已烷"), "环己烷"),
    (re.compile(r"环已烯"), "环己烯"),
    # ``酰胶`` is 酰 + 胶 for 酰 + 胺; only repaired next to the acyl radical so a
    # genuine 胶 (glue/gum) elsewhere is untouched.
    (re.compile(r"酰胶"), "酰胺"),
)


def normalise_ocr_text(text: str) -> str:
    """Repair the deterministic OCR substitutions in *text*.

    Pure and idempotent: running it twice changes nothing more than running it
    once, and text with no known corruption is returned unchanged. Anything the
    substitution table does not recognise is passed through untouched — this
    function never guesses at a digit or a chemical name.
    """
    if not text:
        return text

    def _unit(match: re.Match[str]) -> str:
        # The trailing glyph is the uncertain one: ``mmol`` may arrive as
        # ``mmo1``/``mmol``/``mmoI``. Normalise it to ``l`` and look the whole
        # token up, so an unknown unit is left alone rather than half-rewritten.
        raw = match.group("unit")
        stem = raw[:-1]
        canonical = _UNIT_CANON.get(stem)
        if canonical is None:
            return match.group(0)
        return f"{match.group('value')}{canonical}"

    def _spaced_unit(match: re.Match[str]) -> str:
        # Drop the tracking spaces, then treat it as an ordinary token so both
        # forms resolve through one table.
        collapsed = re.sub(r"\s+", "", match.group("unit"))
        canonical = _UNIT_CANON.get(collapsed[:-1])
        return canonical if canonical is not None else match.group(0)

    repaired = _QUANTITY_UNIT.sub(_unit, text)
    repaired = _SPACED_UNIT.sub(_spaced_unit, repaired)
    repaired = _BARE_UNIT.sub(
        lambda m: _UNIT_CANON.get(m.group("unit")[:-1], m.group(0)), repaired
    )
    repaired = _ADDUCT_PLUS.sub(r"\1+", repaired)
    repaired = _IC50_GLYPH.sub("IC50", repaired)
    repaired = _DASH_FAMILY.sub("-", repaired)
    for pattern, correct in _CHEM_HOMOGLYPHS:
        repaired = pattern.sub(correct, repaired)
    return repaired


#: Corruption the table above does not cover, kept here so a caller can report
#: what remains instead of implying the text is now clean.
RESIDUAL_UNCERTAINTY: Final[tuple[str, ...]] = (
    "misread digits (a value that differs from the printed one)",
    "wrong characters inside a chemical name",
    "glyphs absent from the substitution table",
)


__all__ = ["RESIDUAL_UNCERTAINTY", "normalise_ocr_text"]

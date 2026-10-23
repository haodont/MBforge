"""The OCR substitution table repairs exactly what it claims, and nothing else.

Functions under test: ``mbforge.foundation.inference.ocr.normalise.normalise_ocr_text``.

Measured over the 13-document corpus (10,592 text evidence rows), a scanned
chemistry patent corrupts text in a small, repeatable set of ways: the unit
``mmol`` loses its final ``l`` to a ``1`` (1253 occurrences), an adduct's
superscript ``+`` becomes a dagger (573), and a Japanese-font page is rendered
with tracking that splits units into ``m mo1``. A substitution table repairs
these exactly, which is why no model is spent on them.

The tests below pin both halves of that contract: the corruptions are repaired,
and text that merely *looks* similar is left alone. A false repair here would
silently rewrite a chemical formula or a quantity, which is worse than the
original OCR error.
"""

from __future__ import annotations

from mbforge.foundation.inference.ocr.normalise import normalise_ocr_text


def test_unit_lost_its_l_to_a_one() -> None:
    """``mmo1`` / ``mo1`` become ``mmol`` / ``mol``.

    This is the single most frequent corruption in the corpus (1253 + 84
    occurrences). The same glyph is read correctly in ``mL`` 2060 times and
    wrongly twice, so the error is contextual and a table fixes it exactly.
    """
    assert normalise_ocr_text("3.57mmo1") == "3.57mmol"
    assert normalise_ocr_text("1.95mmo1") == "1.95mmol"
    assert normalise_ocr_text("5.1mo1") == "5.1mol"
    assert normalise_ocr_text("0.5μmo1") == "0.5μmol"
    assert normalise_ocr_text("2nmo1") == "2nmol"


def test_concentration_denominator_without_a_quantity_is_repaired() -> None:
    """``mo1/L`` and ``mo1%`` carry a unit but no numeric prefix of their own."""
    assert normalise_ocr_text("2mo1/L") == "2mol/L"
    assert normalise_ocr_text("(1mo1/L)") == "(1mol/L)"
    assert normalise_ocr_text("0.5 mo1%") == "0.5mol%"


def test_adduct_superscript_plus_is_repaired() -> None:
    """``[M+H]†`` / ``[M+H]⁺`` become ``[M+H]+`` so mass parsing sees the charge.

    The dagger is the most common variant (573 occurrences); downstream code
    matches a literal ``+`` when deciding the adduct, so an unrepaired glyph
    silently drops the mass line.
    """
    assert normalise_ocr_text("LC-MS,M/Z(ESI):247.2[M+H]†") == (
        "LC-MS,M/Z(ESI):247.2[M+H]+"
    )
    assert normalise_ocr_text("[M-H]⁺") == "[M-H]+"
    assert normalise_ocr_text("[M+H]+") == "[M+H]+"


def test_tracking_split_unit_is_repaired() -> None:
    """A spaced-out page yields ``m mo1``, which is one unit, not two tokens."""
    assert normalise_ocr_text("26.3 m mo1") == "26.3mmol"
    assert normalise_ocr_text("0.59 m mo1") == "0.59mmol"


def test_correct_text_is_never_rewritten() -> None:
    """Similar-looking but correct text must pass through untouched.

    A false positive here rewrites a formula or a quantity; the original OCR
    error is the lesser problem.
    """
    untouched = [
        "12.5mL 与 2060mL",
        "chemical name here",
        "C26H26ClF3N4O3S",
        "化合物77-A",
        "1H-吡唑-4-甲酰胺",
        "",
    ]
    for text in untouched:
        assert normalise_ocr_text(text) == text


def test_a_longer_word_ending_in_the_unit_shape_is_not_rewritten() -> None:
    """``emo1`` inside a garbled name is not a unit and must survive."""
    assert normalise_ocr_text("emo1xyz") == "emo1xyz"


def test_normalisation_is_idempotent() -> None:
    """Running it twice must not change the result again."""
    sample = "3.57mmo1 [M+H]† 2mo1/L 化合物77—A"
    once = normalise_ocr_text(sample)
    assert normalise_ocr_text(once) == once


def test_chemistry_homoglyphs_are_repaired_so_names_can_parse() -> None:
    """``环已基`` must become ``环己基`` or the whole name is unparseable.

    ``已``/``己``/``巳`` share a skeleton and the corpus confirms the confusion is
    systematic: 78 occurrences of ``环已基`` against 105 of the correct form. A
    chemical name carrying ``已`` is an unknown character to the name parser, so the
    structure behind it is lost — measured on CN120329282A, all 23 example headings
    print a full systematic name and 0 of 23 could be turned into a structure,
    with ``环已基`` accounting for the majority.
    """
    assert normalise_ocr_text("环已基") == "环己基"
    assert normalise_ocr_text("环巳基") == "环己基"
    assert normalise_ocr_text("已烷") == "己烷"
    assert normalise_ocr_text("环已烷") == "环己烷"
    assert normalise_ocr_text("酰胶") == "酰胺"
    # Correct text is untouched.
    assert normalise_ocr_text("环己基") == "环己基"
    assert normalise_ocr_text("己烷") == "己烷"


def test_a_reading_is_not_broken_by_the_homoglyph_table() -> None:
    """The repair must not touch a mass or a unit that merely contains the shape."""
    assert normalise_ocr_text("3.57mmol") == "3.57mmol"
    assert normalise_ocr_text("[M+H]+") == "[M+H]+"

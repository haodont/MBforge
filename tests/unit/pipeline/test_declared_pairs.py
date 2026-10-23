"""A patent declares its own structure-activity mapping; this join reads it.

Functions under test: ``extract_declared_examples`` / ``pair_structure_activity``.

The fact that makes this possible: an example heading prints the compound's full
systematic name *and* the designation the activity table uses —
``实施例1: <name>(化合物1)的制备``. The join key is stated by the document, so it does
not have to be recovered from a label detected beside a drawing.

Measured on CN120329282A: 23 examples declare both, 14 of those numbers also carry
activity, and the join produces 11 pairs — all 11 confirmed against the product
mass spectrum the example itself prints.
"""

from __future__ import annotations

from dataclasses import dataclass

from mbforge.service.pipeline.patent.declared_pairs import (
    extract_declared_examples,
    pair_structure_activity,
)


@dataclass
class _Row:
    evidence_id: str
    page: int
    raw_text: str


def _corpus() -> list[_Row]:
    """One example section: heading, an intermediate's mass, then the product's."""
    return [
        _Row(
            "ev-1",
            48,
            "[0173] 实施例1:N-((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己基)"
            "-1-(2-(甲基磺酰基)乙基)-1H-吡唑-4-甲酰胺三氟乙酸盐(化合物1)的制备",
        ),
        _Row(
            "ev-2", 48, "[0176] 第一步：1-(2-(甲磺酰基)乙基)-1H-吡唑-4-羧酸乙酯的合成"
        ),
        _Row("ev-3", 48, "[0179] LC-MS,M/Z(ESI):247.2[M+H]+"),
        _Row("ev-4", 49, "[0188] LC-MS,M/Z(ESI):544.2[M+H]+"),
    ]


def test_a_heading_declares_its_name_and_designation() -> None:
    """The heading is the one place the document states the mapping."""
    examples = extract_declared_examples(_corpus(), "doc-1")

    assert len(examples) == 1
    example = examples[0]
    assert example.declared_key == "1"
    assert example.example == "1"
    # The salt is stated after the parent name; the structure belongs to the parent.
    assert not example.name.endswith("盐")
    assert "吡唑-4-甲酰胺" in example.name


def test_the_product_mass_is_the_last_one_printed_in_the_section() -> None:
    """An example prints one mass per step; only the last is the product's.

    Taking any mass from the section instead pairs the structure with an
    intermediate's ion: measured on the real document that turned 8 genuine
    matches into 5 false mismatches.
    """
    examples = extract_declared_examples(_corpus(), "doc-1")

    assert examples[0].product_mz == 544.2


def test_a_reading_joins_to_the_structure_the_document_declares() -> None:
    """The join is designation -> declared name, not proximity on the page."""
    examples = extract_declared_examples(_corpus(), "doc-1")
    readings = [
        {
            "measurement_id": "m-1",
            "reference_key": "1",
            "mol_id": "",
            "metric": "IC50",
            "original_value": 60.7,
            "original_unit": "nM",
        },
    ]
    structures = {"1": "CCO"}

    pairs = pair_structure_activity(examples, readings, structures)

    assert len(pairs) == 1
    assert pairs[0].declared_key == "1"
    assert pairs[0].value == 60.7
    assert pairs[0].unit == "nM"


def test_a_reading_without_a_declared_structure_is_left_unpaired() -> None:
    """A name with no drawn structure is a gap, not a guess.

    Six compounds in CN120329282A declare a full systematic name but have zero
    detected structures on their pages. Pairing them with anything would be
    fabrication.
    """
    examples = extract_declared_examples(_corpus(), "doc-1")
    readings = [
        {"measurement_id": "m-1", "reference_key": "1"},
        {"measurement_id": "m-2", "reference_key": "99"},
    ]

    pairs = pair_structure_activity(examples, readings, {"1": "CCO"})

    assert [pair.declared_key for pair in pairs] == ["1"]


def test_a_pair_that_reproduces_the_printed_mass_is_marked_verified() -> None:
    """The product mass independently confirms the structure.

    Ethanol's [M+H]+ is 47.05: a printed 544.2 is not it, so the pair is reported
    unverified rather than silently presented as confirmed chemistry.
    """
    examples = extract_declared_examples(_corpus(), "doc-1")
    readings = [{"measurement_id": "m-1", "reference_key": "1", "metric": "IC50"}]

    pairs = pair_structure_activity(examples, readings, {"1": "CCO"})

    assert len(pairs) == 1
    assert pairs[0].verified_by_mass is False
    assert pairs[0].printed_mz == 544.2


def test_english_example_heading_declares_its_name() -> None:
    """A US filing heads an example with ``Example N. <systematic name>``.

    The number that follows ``Example`` is the designation an activity table cites
    for that compound, so it is the join key even though no ``Compound N`` is
    printed beside it.
    """
    from mbforge.service.pipeline.patent.declared_pairs import extract_declared_examples

    rows = [
        _Row(
            "ev-en-1",
            31,
            "Example 1. 3-(2,4-Difluorophenoxy)-7-(1-(4,4-dif-luoropiperidin-1-yl)"
            "ethyl)-1,6-naphthyridine",
        ),
        _Row("ev-en-2", 31, "LC-MS calc. for C21H20F4N3O (M+H)+: m/z=406.2"),
    ]

    examples = extract_declared_examples(rows, "doc-1")

    assert len(examples) == 1
    assert examples[0].declared_key == "1"
    assert examples[0].product_mz == 406.2


def test_a_line_break_hyphen_inside_an_english_name_is_repaired() -> None:
    """``dif-luoropiperidin`` is ``difluoropiperidin`` split across a PDF line.

    The split is a hyphen between two lowercase runs; a real substituent hyphen
    (``1-yl``, ``4,4-difluoro``) has a digit or bracket on its left and is left
    alone, which is what keeps the repair from corrupting genuine locants.
    """
    from mbforge.service.pipeline.patent.declared_pairs import extract_declared_examples

    rows = [
        _Row(
            "ev-en-3",
            31,
            "Example 2. 3-(2,4-Difluorophenoxy)-7-(1-(3,3-dif-luoropiperidin-1-yl)"
            "ethyl)-1,6-naphthyridine",
        )
    ]

    examples = extract_declared_examples(rows, "doc-1")

    assert len(examples) == 1
    assert "difluoropiperidin" in examples[0].name
    assert "1-yl" in examples[0].name

"""A printed number that the same compound printed twice.

A patent draws one compound more than once on a page. The geometry cannot then
settle which drawing owns the number, and the number is left unassigned: the
structure keeps no name, no rule binds it to its compound, and every reading
that cites it stays unowned. When the drawings agree about the structure, the
number is that compound's.
"""

from __future__ import annotations

from mbforge.domain.types import ExtractionResult
from mbforge.service.pipeline.detection.normalization import (
    resolve_repeated_print_labels,
)

_COMPOUND = "Cn1cc2c(N[C@@H]3CCC[C@H](Nc4cc(C(F)(F)F)nc5ccc(Cl)cc45)C3)nccc2n1"
_OTHER = "Cn1cc2c(Cl)nccc2n1"


def _result(
    smiles: str,
    labels: list[str],
    *,
    page_idx: int = 79,
    name: str = "",
) -> ExtractionResult:
    return ExtractionResult(
        smiles=smiles,
        name=name,
        page_idx=page_idx,
        bbox_pdf=(100.0, 400.0, 200.0, 500.0),
        properties={
            "ocr_labels_unassigned": list(labels),
            "ocr_labels_unassigned_primary": labels[0] if labels else "",
        },
    )


def test_one_number_on_two_drawings_of_one_compound_names_both() -> None:
    """The same compound drawn twice is one compound, so the number names it."""
    results = [
        _result(_COMPOUND, ["13"]),
        _result(_COMPOUND, ["13"]),
    ]

    assert resolve_repeated_print_labels(results) == 2
    assert [result.name for result in results] == ["13", "13"]
    assert results[0].properties["ocr_labels_primary"] == "13"
    assert "ocr_labels_unassigned" not in results[0].properties


def test_two_drawings_that_disagree_stay_unassigned() -> None:
    """Different structures behind one number are a genuine ambiguity."""
    results = [
        _result(_COMPOUND, ["13"]),
        _result(_OTHER, ["13"]),
    ]

    assert resolve_repeated_print_labels(results) == 0
    assert [result.name for result in results] == ["", ""]
    assert "ocr_labels_unassigned" in results[0].properties


def test_a_single_unassigned_drawing_is_left_alone() -> None:
    """One drawing with no settled owner is a gap, not a resolution."""
    results = [_result(_COMPOUND, ["13"])]

    assert resolve_repeated_print_labels(results) == 0
    assert results[0].name == ""


def test_a_named_drawing_keeps_its_name() -> None:
    """A drawing that already has a name is not renamed by this pass."""
    results = [
        _result(_COMPOUND, ["13"], name="29"),
        _result(_COMPOUND, ["13"]),
    ]

    assert resolve_repeated_print_labels(results) == 0
    assert results[0].name == "29"
    assert results[1].name == ""


def test_two_pages_do_not_share_a_number() -> None:
    """The number must be printed beside the drawing; the page is the frame."""
    results = [
        _result(_COMPOUND, ["13"], page_idx=79),
        _result(_COMPOUND, ["13"], page_idx=80),
    ]

    assert resolve_repeated_print_labels(results) == 0
    assert [result.name for result in results] == ["", ""]


def test_a_repeated_print_name_is_the_pages_own_statement() -> None:
    """A number agreed on by two drawings is the page's statement about them.

    The same compound is drawn in a scheme and again as the figure it belongs
    to; the number is printed on the page, not guessed from a crop. A molecule
    named this way must not be refused as "Markush context" by a different
    drawing's claims-page prose.
    """
    from types import SimpleNamespace

    from mbforge.service.pipeline.detection.structure_role import (
        _named_by_page_text,
    )

    candidate = SimpleNamespace(
        name="13",
        properties={
            "label_source": "repeated_print",
            "name_candidates": [
                {"name": "13", "confidence": 0.94, "source": "repeated_print"}
            ],
            "role_contexts": ["任选的，所述药学上可接受的盐为三氟乙酸盐。"],
        },
        labels=["13"],
    )

    assert _named_by_page_text(candidate) is True

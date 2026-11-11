"""Naming a drawing from the number the page prints beside it.

The contract under test is
``mbforge.service.pipeline.detection.text_label_assignment``: a page's own text
carries the compound numbers a US application prints beside its drawings, and
the drawings must end up named from there.

The boxes below are the real ones of ``US20210128561A1`` p7 (PDF points,
bottom-left origin): two columns of drawings, each number printed at the head
of its own drawing, in the gutter between the columns. That gutter is narrow
enough that the number sits almost as close to the *neighbouring* column's
drawing as to its own — which is why the page has to be matched as a whole
(one number names one drawing, one drawing carries one number) instead of
number by number.
"""

from __future__ import annotations

from mbforge.service.pipeline.detection.text_label_assignment import (
    assign_text_labels,
    bare_designation,
    page_designations,
    to_top_down,
)

#: The printed page height (PDF points).
_PAGE_HEIGHT = 792.0

#: US20210128561A1 p7, left column: two drawings and the numbers at their head.
_LEFT_DRAWINGS = [
    (132.84, 550.44, 225.72, 650.88),
    (131.40, 409.68, 227.88, 525.24),
]
_RIGHT_DRAWINGS = [
    (354.60, 574.92, 469.08, 651.96),
    (354.60, 471.96, 469.08, 561.96),
]
#: The numbers, in the gutter to the right of each column's drawings.
_NUMBERS = [
    ("A-5", (279.92, 648.72, 296.12, 659.23)),
    ("A-6", (277.62, 520.02, 298.98, 537.15)),
    ("A-11", (510.62, 648.31, 530.73, 660.01)),
    ("A-12", (510.43, 559.35, 531.46, 571.93)),
]


def _regions(*items: tuple[str, tuple[float, float, float, float]]) -> list[dict]:
    return [{"kind": "text", "bbox": bbox, "text": text} for text, bbox in items]


def _structures() -> list[tuple[str, tuple[float, float, float, float]]]:
    drawings = _LEFT_DRAWINGS + _RIGHT_DRAWINGS
    return [
        (str(index), to_top_down(bbox, _PAGE_HEIGHT))
        for index, bbox in enumerate(drawings)
    ]


def test_only_a_bare_token_names_a_drawing() -> None:
    """A number the document prints on its own names a drawing; a phrase that
    mentions one does not, and a bare figure is not a compound."""
    assert bare_designation("A-5") == "A-5"
    assert bare_designation("化合物7") == "化合物7"
    assert bare_designation("  A-5  ") == "A-5"
    # A phrase mentions compounds without printing one.
    assert bare_designation("目标化合物11的制备") is None
    assert (
        bare_designation("A-5 to A-30 and the physiologically acceptable salts") is None
    )
    # A paragraph marker and a step are numbers the document uses for
    # something else.
    assert bare_designation("[0331]") is None
    assert bare_designation("1") is None
    assert bare_designation("") is None


def test_page_reads_carry_only_the_numbers_the_page_prints() -> None:
    """The page's text becomes reads; the phrases around it do not."""
    regions = _regions(
        *_NUMBERS,
        ("目标化合物11的制备", (74.23, 369.15, 296.40, 391.48)),
        ("[0331]", (61.43, 100.0, 99.08, 118.0)),
    )

    reads = page_designations(regions, _PAGE_HEIGHT)

    assert [read.text for read in reads] == ["A-5", "A-6", "A-11", "A-12"]
    # The reads carry the position they are printed at.
    assert reads[0].bbox[0] == 279.92


def test_each_number_keeps_the_drawing_of_its_own_column() -> None:
    """The gutter is narrow: a number sits almost as close to the neighbouring
    column's drawing as to its own. The page is matched as a whole, so every
    number keeps the drawing of its own column."""
    reads = page_designations(_regions(*_NUMBERS), _PAGE_HEIGHT)

    assignment = assign_text_labels(_structures(), reads)

    assert assignment.contested == ()
    assert assignment.assignments == {
        "A-5": "0",
        "A-6": "1",
        "A-11": "2",
        "A-12": "3",
    }


def test_a_number_without_a_drawing_is_reported_not_attached() -> None:
    """A printed number that stands clear of every drawing is left out of the
    assignment instead of claiming the nearest one."""
    reads = page_designations(
        _regions(("A-99", (40.0, 700.0, 60.0, 712.0))), _PAGE_HEIGHT
    )

    assignment = assign_text_labels(_structures(), reads)

    assert assignment.assignments == {}
    assert assignment.contested == ("A-99",)


def test_a_number_keeps_its_own_column_even_when_the_next_one_is_closer() -> None:
    """The gutter between two columns is narrow, and the next column's drawing
    can be closer to a number than its own column's drawing.

    The number is printed in the gutter *after* its own column, so it keeps the
    drawing of that column: a compound list numbers its compounds down the
    column they are drawn in.
    """
    left_column = [
        ("0", (76.0, 298.0, 175.0, 360.0)),
        ("1", (76.0, 215.0, 175.0, 280.0)),
    ]
    right_column = [
        ("2", (310.0, 296.0, 409.0, 358.0)),
    ]
    structures = [
        (structure_id, to_top_down(bbox, _PAGE_HEIGHT))
        for structure_id, bbox in [*left_column, *right_column]
    ]
    # The number sits in the gutter, much closer to the right column's drawing
    # than to the left column's.
    reads = page_designations(
        _regions(("B-46", (277.0, 360.0, 294.0, 372.0))), _PAGE_HEIGHT
    )

    assignment = assign_text_labels(structures, reads)

    assert assignment.assignments == {"B-46": "0"}
    assert assignment.contested == ()

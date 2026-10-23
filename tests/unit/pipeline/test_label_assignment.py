"""Spatial label→structure assignment — the ``assign_labels`` contract.

The function under test is
``mbforge.service.pipeline.detection.label_assignment.assign_labels``: one page's
drawing boxes plus that page's printed-number reads in, one ``label →
structure`` assignment out, with ambiguous and unattached cases reported rather
than guessed.

The layouts below are synthetic boxes in one page frame (origin top-left, y
down), which is all the function reads. They reproduce the failure this module
replaces: a fixed 15%-expanded OCR window
(``_OCR_WINDOW_EXPAND_FRACTION`` in ``extraction.crop_processor``) lets one
printed number sit inside two different structures' windows, which is how a
300 DPI render produced 31 labels shared by two different structures.
"""

from __future__ import annotations

from mbforge.service.pipeline.detection.label_assignment import (
    BBox,
    LabelRead,
    OffsetClass,
    StructureBox,
    assign_labels,
)

#: The expansion the module replaces, copied from ``crop_processor``.
_LEGACY_EXPAND_FRACTION = 0.15


def _structures(*items: tuple[str, BBox]) -> list[StructureBox]:
    return [
        StructureBox(structure_id=structure_id, bbox=bbox)
        for structure_id, bbox in items
    ]


def _labels(*items: tuple[str, BBox]) -> list[LabelRead]:
    return [LabelRead(text=text, bbox=bbox) for text, bbox in items]


def _expanded_window(bbox: BBox, fraction: float = _LEGACY_EXPAND_FRACTION) -> BBox:
    x0, y0, x1, y1 = bbox
    pad_x = (x1 - x0) * fraction
    pad_y = (y1 - y0) * fraction
    return (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)


def _overlaps(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _legacy_owner_map(
    structures: list[StructureBox], labels: list[LabelRead]
) -> dict[str, tuple[str, ...]]:
    """Map each printed number to every structure whose expanded window reads it.

    This is the heuristic being replaced: any identifier found in the window is
    taken as that structure's own name, so a number near two drawings is claimed
    by both.
    """
    owners: dict[str, list[str]] = {}
    for structure in structures:
        window = _expanded_window(structure.bbox)
        for label in labels:
            if _overlaps(window, label.bbox):
                owners.setdefault(label.text, []).append(structure.structure_id)
    return {text: tuple(ids) for text, ids in owners.items()}


def test_printed_number_above_drawing_is_assigned_to_it() -> None:
    """Two drawings whose numbers are printed above them, one number each.

    Also covers a repeated OCR read of the same print: the duplicate spelling of
    ``20`` is one designation, not two claimants, so it must not manufacture
    ambiguity.
    """
    structures = _structures(
        ("A", (100.0, 200.0, 300.0, 400.0)),
        ("B", (340.0, 200.0, 540.0, 400.0)),
    )
    labels = _labels(
        ("20", (185.0, 150.0, 215.0, 175.0)),
        ("20", (185.0, 150.0, 215.0, 175.0)),
        ("21", (425.0, 150.0, 455.0, 175.0)),
    )

    result = assign_labels(structures, labels)

    assert result.assignments == {"20": "A", "21": "B"}
    assert result.ambiguous == {}
    assert result.unassigned_labels == ()
    assert result.unlabeled_structures == ()
    assert result.convention is not None
    assert result.convention.offset_classes == frozenset({OffsetClass.ABOVE})
    assert result.convention.support == 2


def test_printed_number_left_of_drawing_is_assigned_to_it() -> None:
    """A column of drawings numbered to the left, the other common convention.

    The same geometry that reads an above-numbered page must read this one,
    because the convention is inferred from the page instead of hard-coded.
    """
    structures = _structures(
        ("A", (300.0, 100.0, 500.0, 300.0)),
        ("B", (300.0, 360.0, 500.0, 560.0)),
        ("C", (300.0, 620.0, 500.0, 820.0)),
    )
    labels = _labels(
        ("1", (240.0, 180.0, 270.0, 205.0)),
        ("2", (240.0, 440.0, 270.0, 465.0)),
        ("3", (240.0, 700.0, 270.0, 725.0)),
    )

    result = assign_labels(structures, labels)

    assert result.assignments == {"1": "A", "2": "B", "3": "C"}
    assert result.ambiguous == {}
    assert result.unlabeled_structures == ()
    assert result.convention is not None
    assert result.convention.offset_classes == frozenset({OffsetClass.LEFT})
    assert result.convention.support == 3


def test_shared_horizontal_band_separates_numbers_the_expanded_window_crosses() -> None:
    """The 300 DPI failure mode: two drawings in one band, two numbers.

    ``21`` is printed above ``B`` but also falls inside ``A``'s 15%-expanded
    window, so the window rule reads it as ``A``'s name as well — one label on
    two different structures, which association reports as
    ``molecule_candidate_ambiguous`` and which collapsed attribution from 58% to
    zero. Geometry assigns both numbers to the drawing that owns them.
    """
    structures = _structures(
        ("A", (100.0, 200.0, 300.0, 400.0)),
        ("B", (320.0, 200.0, 520.0, 400.0)),
    )
    labels = _labels(
        ("20", (100.0, 165.0, 130.0, 190.0)),
        ("21", (320.0, 165.0, 350.0, 190.0)),
    )

    legacy = _legacy_owner_map(structures, labels)
    assert legacy["21"] == ("A", "B"), "the window rule must cross the two drawings"
    assert legacy["20"] == ("A",)

    result = assign_labels(structures, labels)

    assert result.assignments == {"20": "A", "21": "B"}
    assert result.ambiguous == {}
    assert result.unlabeled_structures == ()
    # Reading order is derived from the boxes, so the caller's input order
    # cannot change who owns a number.
    assert assign_labels(
        list(reversed(structures)), list(reversed(labels))
    ).assignments == {"20": "A", "21": "B"}


def test_number_equidistant_between_two_drawings_is_reported_ambiguous() -> None:
    """Contests are reported in both directions: one number, or one drawing.

    A number printed between two drawings names neither of them, and a drawing
    with two equally close numbers has no answer either — in both cases picking
    one would be the original bug with extra steps, so the review queue owns it.
    """
    two_drawings = _structures(
        ("A", (100.0, 200.0, 300.0, 400.0)),
        ("B", (340.0, 200.0, 540.0, 400.0)),
    )

    result = assign_labels(two_drawings, _labels(("20", (307.0, 150.0, 333.0, 175.0))))

    assert result.assignments == {}
    assert result.ambiguous == {"20": ("A", "B")}
    assert result.unassigned_labels == ()
    assert result.unlabeled_structures == ("A", "B")
    # Nothing on the page settled a layout, so no convention may be claimed.
    assert result.convention is None

    one_drawing = _structures(("A", (300.0, 200.0, 500.0, 400.0)))
    contested = assign_labels(
        one_drawing,
        _labels(
            ("20", (355.0, 150.0, 380.0, 175.0)),
            ("21", (420.0, 150.0, 445.0, 175.0)),
        ),
    )

    assert contested.assignments == {}
    assert contested.ambiguous == {"20": ("A",), "21": ("A",)}
    assert contested.unlabeled_structures == ("A",)


def test_drawing_without_nearby_number_stays_unlabeled() -> None:
    """A number elsewhere on the page is not this drawing's number.

    A drawing with no print beside it stays unlabeled rather than borrowing a
    distant number: a wrong name is worse than no name, because a wrong name
    links its activity reading to the wrong structure.
    """
    structures = _structures(("A", (100.0, 200.0, 300.0, 400.0)))
    labels = _labels(("7", (700.0, 700.0, 730.0, 725.0)))

    result = assign_labels(structures, labels)

    assert result.assignments == {}
    assert result.ambiguous == {}
    assert result.unassigned_labels == ("7",)
    assert result.unlabeled_structures == ("A",)


def test_convention_is_inferred_from_the_page_not_hard_coded() -> None:
    """The same three drawings read correctly under every print convention.

    Patents differ per document: numbers above the drawing, below it, to the
    left, or inline. Only the settled cases move, so a page must adapt — and an
    inline-numbered page must not be read through the above-numbered rule.

    The rows are 300 pt apart and a drawing is 200 pt tall, so the 40 pt number
    printed below one drawing sits in the gutter and clips the next drawing's
    top edge. That clipped read must not become convention evidence: if it did,
    the page would infer ``INSIDE``/``ABOVE`` from it and the ``BELOW`` numbers
    would assign to the drawing above them.
    """
    structures = _structures(
        ("A", (300.0, 100.0, 500.0, 300.0)),
        ("B", (300.0, 340.0, 500.0, 540.0)),
        ("C", (300.0, 580.0, 500.0, 780.0)),
    )
    conventions: list[tuple[OffsetClass, list[tuple[str, BBox]]]] = [
        (
            OffsetClass.ABOVE,
            [
                ("1", (385.0, 55.0, 415.0, 80.0)),
                ("2", (385.0, 295.0, 415.0, 320.0)),
                ("3", (385.0, 535.0, 415.0, 560.0)),
            ],
        ),
        (
            OffsetClass.BELOW,
            [
                ("1", (385.0, 320.0, 415.0, 345.0)),
                ("2", (385.0, 560.0, 415.0, 585.0)),
                ("3", (385.0, 800.0, 415.0, 825.0)),
            ],
        ),
        (
            OffsetClass.LEFT,
            [
                ("1", (255.0, 160.0, 285.0, 185.0)),
                ("2", (255.0, 400.0, 285.0, 425.0)),
                ("3", (255.0, 640.0, 285.0, 665.0)),
            ],
        ),
        (
            OffsetClass.INSIDE,
            [
                ("1", (380.0, 180.0, 420.0, 220.0)),
                ("2", (380.0, 420.0, 420.0, 460.0)),
                ("3", (380.0, 660.0, 420.0, 700.0)),
            ],
        ),
    ]

    for convention, label_boxes in conventions:
        result = assign_labels(structures, _labels(*label_boxes))
        assert result.assignments == {"1": "A", "2": "B", "3": "C"}, convention
        assert result.ambiguous == {}, convention
        assert result.unlabeled_structures == (), convention
        assert result.convention is not None, convention
        assert result.convention.offset_classes == frozenset({convention})
        assert result.convention.support >= 1, convention

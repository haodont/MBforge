"""Focused tests for the layout primitives (merge / reading order / text join)."""

from __future__ import annotations

from mbforge.adapters.inference.ocr.page_text import join_lines
from mbforge.application.pipeline.layout.merge import merge
from mbforge.application.pipeline.layout.reading_order import sort_boxes

_PAGE_HEIGHT_PT = 100.0
_PX_PER_PT = 2.0


def _region(
    region_id: str,
    label: str,
    region_type: str,
    bbox_px: tuple[float, float, float, float],
    score: float = 0.9,
) -> dict:
    return {
        "region_id": region_id,
        "doc_id": "doc",
        "page": 1,
        "kind": label,
        "label": label,
        "type": region_type,
        "score": score,
        "source": "layout_hiro",
        "reading_order": 0,
        "bbox_px": [float(value) for value in bbox_px],
        "bbox_pdf": [0.0, 0.0, 0.0, 0.0],
    }


def _molecule(
    region_id: str,
    bbox_px: tuple[float, float, float, float],
    score: float = 0.9,
) -> dict:
    return {
        "region_id": region_id,
        "doc_id": "doc",
        "page": 1,
        "kind": "molecule",
        "label": "molecule",
        "type": "molecule",
        "score": score,
        "source": "molecule_det",
        "reading_order": 0,
        "bbox_px": [float(value) for value in bbox_px],
        "bbox_pdf": [0.0, 0.0, 0.0, 0.0],
    }


def test_merge_keeps_the_higher_scoring_duplicate() -> None:
    """R1: same-label duplicate boxes collapse to the stronger detection."""
    regions, stats = merge(
        [
            _region("a", "text", "text", (0, 0, 100, 20), score=0.80),
            _region("b", "text", "text", (0, 0, 100, 20), score=0.95),
        ],
        page_height_pt=_PAGE_HEIGHT_PT,
        px_per_pt=_PX_PER_PT,
    )

    assert [region["score"] for region in regions] == [0.95]
    assert stats["r1_dup_removed"] == 1


def test_merge_unions_overlapping_text_boxes() -> None:
    """R5: overlapping text boxes merge, so one line is read once, not twice."""
    regions, stats = merge(
        [
            _region("a", "text", "text", (0, 0, 100, 20)),
            _region("b", "cap", "text", (90, 5, 200, 25)),
        ],
        page_height_pt=_PAGE_HEIGHT_PT,
        px_per_pt=_PX_PER_PT,
    )

    assert len(regions) == 1
    assert regions[0]["bbox_px"] == [0.0, 0.0, 200.0, 25.0]
    assert stats["r5_text_merged"] == 1


def test_merge_yields_a_figure_region_to_the_molecule_it_coincides_with() -> None:
    """R3: a figure region covering one molecule becomes that molecule."""
    regions, stats = merge(
        [_region("a", "chem", "image", (10, 10, 110, 110))],
        [_molecule("m", (10, 10, 110, 110))],
        page_height_pt=_PAGE_HEIGHT_PT,
        px_per_pt=_PX_PER_PT,
    )

    assert len(regions) == 1
    assert regions[0]["type"] == "molecule"
    assert regions[0]["kind"] == "molecule"
    assert stats["r3_yielded"] == 1


def test_merge_keeps_a_multi_molecule_figure_as_a_container() -> None:
    """R4: a figure holding several molecules stays one region, not one molecule."""
    regions, stats = merge(
        [_region("a", "chem", "image", (0, 0, 100, 100))],
        [_molecule("m0", (5, 5, 45, 45)), _molecule("m1", (55, 55, 95, 95))],
        page_height_pt=_PAGE_HEIGHT_PT,
        px_per_pt=_PX_PER_PT,
    )

    assert len(regions) == 1
    assert regions[0]["type"] == "image"
    assert [child["kind"] for child in regions[0]["children"]] == [
        "molecule",
        "molecule",
    ]
    assert stats["r4_containers"] == 1
    assert stats["r4_children"] == 2


def test_reading_order_reads_columns_before_raster_order() -> None:
    """A two-column page reads down the left column, then the right."""
    left_top = [0.05, 0.05, 0.30, 0.15]
    right_top = [0.45, 0.06, 0.70, 0.16]
    left_bottom = [0.05, 0.20, 0.30, 0.40]
    right_bottom = [0.45, 0.21, 0.70, 0.41]

    ordered = sort_boxes([left_top, right_top, left_bottom, right_bottom])

    assert ordered == [left_top, left_bottom, right_top, right_bottom]


def test_join_lines_does_not_glue_latin_words_across_lines() -> None:
    """A Latin line break becomes a space; a CJK one does not."""
    assert join_lines(["redness,", "swelling"]) == "redness, swelling"
    assert join_lines(["化合", "物"]) == "化合物"

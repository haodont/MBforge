"""Logical-table grouping contract (continuation fragments).

Protects the rule that a cross-page continuation fragment without its own
header joins its parent table, while a same-width table on the next page does
not: classification runs per logical table because judging a headerless tail
alone loses it.
"""

from __future__ import annotations

from mbforge.service.pipeline.activity.logical_tables import (
    FragmentClass,
    TableFragment,
    classify_logical_table,
    group_fragments,
)


def _fragment(
    page: int,
    *,
    table: int = 1,
    bbox: tuple[float, float, float, float] = (100.0, 80.0, 500.0, 760.0),
    has_header: bool = False,
    caption: str = "",
    source: str = "doc.pdf",
    header_is_data: bool = False,
) -> TableFragment:
    return TableFragment(
        source=source,
        page=page,
        table=table,
        bbox=bbox,
        page_width=595.0,
        page_height=842.0,
        has_header=has_header,
        column_count=4,
        caption=caption,
        header_is_data=header_is_data,
    )


def test_a_headerless_tail_joins_its_parent_but_a_same_width_table_does_not() -> None:
    """p1 bottom → p2 top is a continuation; p2 bottom is a new table."""
    groups = group_fragments(
        [
            # Parent table ends at the page bottom.
            _fragment(1, bbox=(100.0, 30.0, 500.0, 760.0)),
            # Headerless tail starts at the top of page 2 with the same width.
            _fragment(2, bbox=(101.0, 620.0, 501.0, 830.0)),
            # Same width, but it sits at the bottom of page 2: not a tail.
            _fragment(3, bbox=(100.0, 40.0, 500.0, 300.0)),
        ]
    )

    assert [len(group.fragments) for group in groups] == [2, 1]
    assert [fragment.page for fragment in groups[0].fragments] == [1, 2]


def test_a_new_header_or_a_different_width_starts_a_new_table() -> None:
    """A fragment with its own header, or a different printed width, is new."""
    groups = group_fragments(
        [
            _fragment(1, bbox=(100.0, 30.0, 500.0, 760.0)),
            # Headerless and at the page top, but narrower: a different table.
            _fragment(2, bbox=(100.0, 620.0, 360.0, 830.0)),
            # Same width and at the page top, but it prints its own header.
            _fragment(3, bbox=(100.0, 620.0, 500.0, 830.0), has_header=True),
        ]
    )

    assert [len(group.fragments) for group in groups] == [1, 1, 1]


def test_a_continued_caption_links_fragments_without_page_margin_geometry() -> None:
    """An explicit ``continued`` caption is authoritative over the margins."""
    groups = group_fragments(
        [
            _fragment(1, bbox=(100.0, 300.0, 500.0, 600.0)),
            _fragment(
                2,
                bbox=(100.0, 300.0, 500.0, 600.0),
                caption="| TABLE 1-continued |",
            ),
        ]
    )

    assert len(groups) == 1
    assert len(groups[0].fragments) == 2


def test_a_header_fragment_class_propagates_to_a_headerless_tail() -> None:
    """The parent prints the header, so the tail inherits its class."""
    groups = group_fragments(
        [
            _fragment(1, bbox=(100.0, 30.0, 500.0, 760.0)),
            _fragment(2, bbox=(100.0, 620.0, 500.0, 830.0)),
        ]
    )
    assert len(groups) == 1
    classes = {("doc.pdf", 1, 1): FragmentClass(name="activity")}

    assert classify_logical_table(groups[0], classes) == ("activity", "p1t1")


def test_a_headerless_value_shaped_table_is_surfaced_for_review() -> None:
    """No readable header, but values + units: activity? rather than dropped."""
    groups = group_fragments([_fragment(5)])
    classes = {
        ("doc.pdf", 5, 1): FragmentClass(
            name="other", numeric_density=0.4, unit_values=2
        )
    }

    assert classify_logical_table(groups[0], classes) == ("activity?", "content_shape")


def test_a_promoted_data_row_joins_the_previous_table_without_page_margins() -> None:
    """``| 化合物23A | B |`` is data, so the fragment is a continuation.

    The previous table ends at 15% of the page height, outside the bottom margin;
    the promoted data header is what proves the continuation.
    """
    groups = group_fragments(
        [
            _fragment(1, bbox=(100.0, 127.0, 310.0, 166.0)),
            _fragment(
                2,
                bbox=(100.0, 554.0, 310.0, 780.0),
                header_is_data=True,
            ),
        ]
    )

    assert len(groups) == 1
    assert [fragment.page for fragment in groups[0].fragments] == [1, 2]

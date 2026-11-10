"""Function under test: ``select_text_blocks`` from the page-text preview.

The page/model call itself needs the local layout weights, so this test pins
the pure part: region intersection, empty-text removal, reading order and the
truncation flag the capability exposes to the agent.
"""

from __future__ import annotations

import pytest

from mbforge.foundation.errors import ValidationError
from mbforge.service.use_cases.documents.page_text import select_text_blocks


def _region(
    region_id: str,
    bbox: list[float],
    text: str,
    *,
    kind: str = "text",
    order: int = 0,
) -> dict:
    return {
        "region_id": region_id,
        "label": kind,
        "type": kind,
        "bbox_pdf": bbox,
        "reading_order": order,
        "text": text,
    }


def test_select_text_blocks_keeps_only_overlapping_non_empty_regions() -> None:
    regions = [
        _region("left", [10, 10, 100, 50], "alpha", order=1),
        _region("left2", [10, 55, 100, 95], "gamma", order=2),
        _region("right", [200, 200, 300, 250], "beta", order=3),
        _region("empty", [10, 60, 100, 90], "  "),
        _region("figure", [10, 100, 100, 150], "caption", kind="image"),
    ]

    blocks, truncated = select_text_blocks(
        regions, region=[0, 0, 150, 100], max_blocks=1
    )
    assert [block["region_id"] for block in blocks] == ["left"]
    assert truncated is True

    blocks, truncated = select_text_blocks(
        regions, region=[150, 150, 350, 300], max_blocks=10
    )
    assert [block["region_id"] for block in blocks] == ["right"]
    assert truncated is False


def test_select_text_blocks_rejects_a_reversed_region() -> None:
    with pytest.raises(ValidationError):
        select_text_blocks([], region=[100, 100, 10, 10])

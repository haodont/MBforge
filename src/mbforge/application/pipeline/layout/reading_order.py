"""Reading order: the official Hiro-Smart-Doc ``column_sort`` heuristic.

Hiro-Layout does not emit a reading order — the region list is just the model's
forward output order. For a two-column US patent that reads as garbage (the
source project measured a 323 px y-backjump on two-column pages), and MBForge's
own join-time sort is a pure raster sort with no notion of columns.

This module is a **line-by-line port** of the official implementation
(``refs/Hiro-Smart-Doc/.../model_runners/layout.py``, ``column_sort`` +
``determine_columns``); every constant corresponds to a literal in the official
source, with its line number noted. It was validated against the official
implementation as an oracle (7 handcrafted cases + 3000 randomized + 768 real
pages, byte-identical output).

## Coordinates

Everything here is **normalized 0..1, top-left origin, y down** — matching the
official code. Region ``bbox_px`` is already top-left/y-down, so dividing by the
page size lands in the same space.

## Algorithm

1. Sort globally by ``y0`` (pure raster order — only a starting point);
2. ``determine_columns`` decides 1 / 2 / 3 columns from the per-column sum of
   box heights;
3. Distribute by column. The key move is the **back-fill of column-spanning
   boxes**: when a spanning box (e.g. a title) is met, the boxes accumulated in
   the right column are flushed back into the left column, so the title lands
   after the text above it and before the text below. That is exactly what a
   raster sort cannot do.

⚠️ The thresholds are the official magic numbers, tuned by case study. The
official comment itself says "these magic numbers are based on case study and
may need to be tuned". Known limit: on a single-column page with narrow side
notes, ``determine_columns`` can misjudge it as two columns (≈22% of pages still
show intra-column interleaving).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# ---- constants: every one corresponds to a literal in the official layout.py ----
LINE1_SPLITTING = 0.33  # layout.py:84  first/second column boundary (normalized x)
LINE2_SPLITTING = 0.60  # layout.py:84  second/third column boundary
MIN_BOXES_FOR_COLUMN_CHECK = 3  # layout.py:89  fewer than 3 boxes → single column
MIN_BAR_WIDTH = (
    0.1  # layout.py:95  boxes narrower than this don't count toward column height
)
COL_HEIGHT_FLOOR = 0.2  # layout.py:98  lower bound of the column-height threshold
COL_HEIGHT_RATIO = 0.6  # layout.py:98  threshold = min(floor, col1 height × ratio)
SPAN_2COL_LEFT = 0.4  # layout.py:128 two columns: left-half criterion
SPAN_2COL_RIGHT = 0.52  # layout.py:129 two columns: pure col-1 vs spanning title
SPAN_3COL_LEFT = 0.3  # layout.py:142 three columns: col 1 or spanning
SPAN_3COL_MID = 0.6  # layout.py:158 three columns: col 2 or spanning
SPAN_3COL_C1 = 0.4  # layout.py:143 three columns: pure col 1
SPAN_3COL_C2 = 0.66  # layout.py:145 three columns: spans first two vs all three
SPAN_3COL_C3 = 0.66  # layout.py:159 three columns: spans last two


def determine_columns(
    boxes: Sequence[Sequence[float]],
    line1_splitting: float = LINE1_SPLITTING,
    line2_splitting: float = LINE2_SPLITTING,
) -> int:
    """Decide the page's column count (1 / 2 / 3).

    ``boxes`` are normalized ``[x0, y0, x1, y1]``. The criterion is not "which
    column does a box fall in" but the **accumulated box height per column**:
    a column only counts if enough content actually piled up there, which avoids
    false positives from a title spanning the middle.
    """
    if not boxes or len(boxes) < MIN_BOXES_FOR_COLUMN_CHECK:
        return 1

    column1_height = sum(
        abs(box[3] - box[1])
        for box in boxes
        if box[0] < line1_splitting and box[2] - box[0] > MIN_BAR_WIDTH
    )
    column2_height = sum(
        abs(box[3] - box[1])
        for box in boxes
        if line1_splitting < box[0] < line2_splitting
        and box[2] - box[0] > MIN_BAR_WIDTH
    )
    column3_height = sum(
        abs(box[3] - box[1])
        for box in boxes
        if box[0] > line2_splitting and box[2] - box[0] > MIN_BAR_WIDTH
    )

    threshold = min(COL_HEIGHT_FLOOR, column1_height * COL_HEIGHT_RATIO)
    if column3_height > threshold:
        return 3
    if column2_height > threshold:
        return 2
    return 1


def sort_boxes(boxes: list[list[float]]) -> list[list[float]]:
    """Reorder *boxes* in place (matching the official code) and return them.

    ``boxes`` is a **mutable** sequence of normalized ``[x0, y0, x1, y1]`` lists.
    """
    boxes.sort(key=lambda box: box[1])  # official layout.py:111 — global sort by y0
    column_count = determine_columns(boxes)

    if column_count == 1:
        return boxes

    col_1: list[list[float]] = []
    col_2: list[list[float]] = []
    col_3: list[list[float]] = []

    if column_count == 2:
        for box in boxes:
            if box[0] < SPAN_2COL_LEFT:
                if box[2] < SPAN_2COL_RIGHT:
                    col_1.append(box)  # pure first column
                else:
                    col_2.append(box)  # spanning title row
                    col_1.extend(col_2)  # ← back-fill
                    col_2 = []
            else:
                col_2.append(box)  # second column
        return col_1 + col_2

    for box in boxes:
        if box[0] < SPAN_3COL_LEFT:
            if box[2] < SPAN_3COL_C1:
                col_1.append(box)  # pure first column
            elif box[2] < SPAN_3COL_C2:
                col_2.append(box)  # spans first two columns
                col_1.extend(col_2)  # ← back-fill
                col_2 = []
            else:
                col_3.append(box)  # spans all three
                col_1.extend(col_2)  # ← back-fill
                col_1.extend(col_3)
                col_2, col_3 = [], []
        elif box[0] < SPAN_3COL_MID:
            if box[2] > SPAN_3COL_C3:
                col_3.append(box)  # spans last two columns
                col_2.extend(col_3)  # ← back-fill into column 2
                col_3 = []
            else:
                col_2.append(box)  # pure second column
        else:
            col_3.append(box)  # third column
    return col_1 + col_2 + col_3


def assign(
    regions: Sequence[dict[str, Any]], page: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reorder the final region set and write the new index into ``reading_order``.

    Returns a new reordered list; ``region["reading_order"]`` is updated in
    place. The input list itself is not mutated.

    ⚠️ Call this **once**, on the **final** region set. The merge rules delete
    and rewrite regions, so any order assigned before them is invalidated.
    """
    if not regions:
        return list(regions)

    width = float(page["width_px"])
    height = float(page["height_px"])

    work: list[tuple[list[float], dict[str, Any]]] = []
    for region in regions:
        x0, y0, x1, y1 = (float(value) for value in region["bbox_px"])
        work.append(([x0 / width, y0 / height, x1 / width, y1 / height], region))

    ordered_norm = sort_boxes([norm for norm, _ in work])

    # Normalized quadruples can repeat, so map back by identity-bearing list
    # lookup (pop from a per-value bucket) instead of by value equality.
    buckets: dict[tuple[float, ...], list[dict[str, Any]]] = {}
    for norm, region in work:
        buckets.setdefault(tuple(norm), []).append(region)

    result: list[dict[str, Any]] = []
    for norm in ordered_norm:
        result.append(buckets[tuple(norm)].pop(0))

    for index, region in enumerate(result):
        region["reading_order"] = index
    return result


__all__ = [
    "LINE1_SPLITTING",
    "LINE2_SPLITTING",
    "assign",
    "determine_columns",
    "sort_boxes",
]

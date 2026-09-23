"""IoU bbox overlap filter — collapse overlapping boxes to the larger one.

Shared by the join/read paths to merge overlapping molecule boxes. Keeping the
larger box on overlap means a molecule detected multiple times with slightly
shifted/scaled boxes renders once.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

BBox = tuple[float, float, float, float]


def bbox_area(bbox: BBox) -> float:
    """Area (bottom-left points). 0 guards degenerate/zero-size boxes."""
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def bbox_iou(a: BBox, b: BBox) -> float:
    """Intersection-over-union of two bottom-left bboxes."""
    inter_w = min(a[2], b[2]) - max(a[0], b[0])
    inter_h = min(a[3], b[3]) - max(a[1], b[1])
    if inter_w <= 0 or inter_h <= 0:
        return 0.0
    inter = inter_w * inter_h
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def add_bbox_keep_larger(
    kept: list[tuple[BBox, Any]],
    bbox: BBox,
    payload: Any,
    iou_threshold: float = 0.5,
) -> None:
    """Register (bbox, payload) into *kept*, keeping only the larger on overlap.

    When *bbox* overlaps an existing kept box above ``iou_threshold``, the
    larger-area box survives (replaced in place, order stable); otherwise the
    pair is appended. Non-overlapping boxes always append.
    """
    for i, (kbox, _) in enumerate(kept):
        if bbox_iou(kbox, bbox) > iou_threshold:
            if bbox_area(bbox) > bbox_area(kbox):
                kept[i] = (bbox, payload)
            return
    kept.append((bbox, payload))


def dedupe_keep_larger(
    items: Iterable[tuple[BBox, Any]],
    iou_threshold: float = 0.5,
) -> list[tuple[BBox, Any]]:
    """Filter an iterable of (bbox, payload) pairs, larger box wins on overlap.

    Order is preserved and overlapping boxes collapse to the larger one, so
    callers can post-process an already-built list (e.g. source evidence).
    """
    kept: list[tuple[BBox, Any]] = []
    for bbox, payload in items:
        add_bbox_keep_larger(kept, bbox, payload, iou_threshold)
    return kept

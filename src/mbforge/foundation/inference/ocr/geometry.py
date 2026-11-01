"""Shared geometry helpers for the local OCR readers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def tight_box(points: Iterable[Sequence[float]]) -> tuple[int, int, int, int]:
    """Return the integer bounding box of a RapidOCR polygon."""
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))

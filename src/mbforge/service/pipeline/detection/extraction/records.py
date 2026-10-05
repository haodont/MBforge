"""Page records exchanged between the molecule-pass stages.

The molecule pass runs as three stages in three threads:

    PageRenderer -> page queue -> PageDetector -> crop queue -> CropProcessor

These frozen records are what the queues carry. The stages used to exchange
positional tuples (a five-tuple between renderer and detector, a seven-tuple
between detector and crop worker), so every stage had to unpack by position and
recompute the pixel-to-point scale. The records replace that with named fields
and one derivation of the scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class RenderedPage:
    """One rendered PDF page plus the native text blocks read from it.

    "Rendered" is the lifecycle state: the page exists as an image and nothing
    has inspected it yet. Whoever takes it off the queue owns ``image``.
    """

    page_index: int  # 0-based, as PyMuPDF indexes pages
    image: Image.Image
    blocks: object  # PyMuPDF ``get_text("blocks")`` output, or () when unreadable
    width_pt: float
    height_pt: float

    @property
    def scale_x(self) -> float:
        """Image pixels to PDF points along x (0 when the render is empty)."""
        return self.width_pt / self.image.width if self.image.width > 0 else 0.0

    @property
    def scale_y(self) -> float:
        """Image pixels to PDF points along y (0 when the render is empty)."""
        return self.height_pt / self.image.height if self.image.height > 0 else 0.0


@dataclass(frozen=True)
class DetectedPage:
    """A rendered page plus the molecule boxes MolDet found on it."""

    page: RenderedPage
    bboxes: list[Any]

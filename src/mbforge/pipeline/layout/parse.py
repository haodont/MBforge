"""Layout-driven page parsing: render → detect → merge → reading order → text.

This is the orchestration the Extract branch uses when the local layout
detector is enabled. It produces one :class:`LayoutPage` per PDF page, each
carrying the merged/ordered region list with ``raw_text`` filled in for text
regions.

Pipeline inside one page:

    render (144 DPI)  →  Hiro-Layout regions  →  merge R1/R2/R5
                      →  column_sort reading order  →  layout-guided text OCR

One render per page is reused by both the detector and the text recognizer, so
the two never disagree about geometry (the fixed 2 px/pt mapping shared with
``LayoutSpan`` and ``SourceEvidence``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mbforge.utils.logger import get_logger

from .labels import TEXT_REGION_TYPES
from .merge import merge
from .reading_order import assign as assign_reading_order
from .regions import build_regions, px_per_pt

logger = get_logger(__name__)

#: Contract render zoom: 2 px/pt = 144 DPI (matches ``_OCR_RENDER_ZOOM``).
DEFAULT_RENDER_ZOOM = 2.0

#: Detector confidence threshold (the source project's measured working point).
DEFAULT_CONF = 0.4


class LayoutUnavailableError(RuntimeError):
    """The local layout detector could not run (missing weights / onnxruntime).

    Raised instead of silently returning empty pages: a layout-driven run must
    fail loudly rather than produce a document with no evidence.
    """


@dataclass
class LayoutPage:
    """One parsed page: merged regions plus the page frame they live in."""

    page_num: int  # 1-based
    width_pt: float
    height_pt: float
    dpi: float
    regions: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def render_page_rgb(page: Any, zoom: float = DEFAULT_RENDER_ZOOM) -> np.ndarray:
    """Render one PyMuPDF page to an HWC uint8 RGB array at *zoom* px/pt."""
    import pymupdf

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    array = np.frombuffer(pixmap.samples, dtype=np.uint8)
    return array.reshape(pixmap.height, pixmap.width, pixmap.n)[:, :, :3].copy()


def parse_page_image(
    image: np.ndarray,
    *,
    doc_id: str,
    page_num: int,
    zoom: float = DEFAULT_RENDER_ZOOM,
    detector: Any | None = None,
    conf: float = DEFAULT_CONF,
    read_text: bool = True,
    params: dict[str, Any] | None = None,
) -> LayoutPage:
    """Detect, merge, order and (optionally) read one already-rendered page.

    ``image`` is HWC uint8 **RGB** at *zoom* px/pt.
    """
    from mbforge.backends.hiro_layout import detect_regions

    dpi = float(zoom) * 72.0
    scale = px_per_pt(dpi)
    height_px, width_px = float(image.shape[0]), float(image.shape[1])

    boxes = detect_regions(image, detector, threshold=conf)
    regions, page_frame = build_regions(
        boxes,
        doc_id=doc_id,
        page=page_num,
        page_size_px=(width_px, height_px),
        dpi=dpi,
    )
    regions, merge_stats = merge(
        regions,
        page_height_pt=page_frame["height_pt"],
        px_per_pt=scale,
        params=params,
    )
    # Reading order must be assigned once, on the final post-merge set.
    regions = assign_reading_order(regions, page_frame)

    text_stats = _fill_text(regions, image) if read_text else {"text_regions": 0}

    return LayoutPage(
        page_num=page_num,
        width_pt=page_frame["width_pt"],
        height_pt=page_frame["height_pt"],
        dpi=dpi,
        regions=regions,
        stats={
            "detected": len(boxes),
            "regions": len(regions),
            **merge_stats,
            **text_stats,
        },
    )


def _fill_text(regions: list[dict[str, Any]], image: np.ndarray) -> dict[str, int]:
    """Recognize text inside text regions and store it on each region."""
    text_regions = [r for r in regions if str(r.get("type")) in TEXT_REGION_TYPES]
    if not text_regions:
        return {"text_regions": 0}

    from mbforge.backends.ocr.page_text import read_text_in_boxes

    boxes = [(str(r["region_id"]), r["bbox_px"]) for r in text_regions]
    try:
        recognized = read_text_in_boxes(image, boxes)
    except Exception as exc:  # noqa: BLE001 — enrichment must never break a run
        logger.warning("Layout text recognition failed: %s", exc)
        recognized = {}

    filled = 0
    for region in text_regions:
        text = (recognized.get(str(region["region_id"])) or "").strip()
        region["text"] = text
        filled += 1 if text else 0
    return {"text_regions": len(text_regions), "text_filled": filled}


def parse_pdf_layout(
    pdf_path: str | Path,
    *,
    doc_id: str,
    zoom: float = DEFAULT_RENDER_ZOOM,
    detector: Any | None = None,
    conf: float = DEFAULT_CONF,
    read_text: bool = True,
    max_pages: int | None = None,
    cancel_check: Any | None = None,
    params: dict[str, Any] | None = None,
) -> list[LayoutPage]:
    """Parse every page of a PDF through the local layout pipeline."""
    import pymupdf

    pages: list[LayoutPage] = []
    document = pymupdf.open(str(pdf_path))
    try:
        count = document.page_count
        if max_pages is not None:
            count = min(count, max_pages)
        for index in range(count):
            if cancel_check is not None:
                cancel_check()
            page = document.load_page(index)
            image = render_page_rgb(page, zoom)
            parsed = parse_page_image(
                image,
                doc_id=doc_id,
                page_num=index + 1,
                zoom=zoom,
                detector=detector,
                conf=conf,
                read_text=read_text,
                params=params,
            )
            pages.append(parsed)
            logger.info(
                "Layout page %d/%d: %d regions (%d text)",
                index + 1,
                count,
                len(parsed.regions),
                parsed.stats.get("text_filled", 0),
            )
    finally:
        document.close()
    return pages


def layout_region_kind_vocab() -> dict[str, str]:
    """The ``{label: category}`` vocabulary a layout artifact must declare."""
    from .labels import kind_vocab

    return kind_vocab()


def text_region_boxes(
    regions: Sequence[dict[str, Any]],
) -> list[tuple[str, list[float]]]:
    """``(region_id, bbox_px)`` of every text region (for external OCR callers)."""
    return [
        (str(region["region_id"]), list(region["bbox_px"]))
        for region in regions
        if str(region.get("type")) in TEXT_REGION_TYPES
    ]


__all__ = [
    "DEFAULT_CONF",
    "DEFAULT_RENDER_ZOOM",
    "LayoutPage",
    "LayoutUnavailableError",
    "layout_region_kind_vocab",
    "parse_page_image",
    "parse_pdf_layout",
    "render_page_rgb",
    "text_region_boxes",
]

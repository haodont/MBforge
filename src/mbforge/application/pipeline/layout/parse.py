"""Layout-driven page parsing: render → detect → merge → reading order → text.

This is the orchestration the Extract branch uses when the local layout
detector is enabled. It produces one :class:`LayoutPage` per PDF page, each
carrying the merged/ordered region list with ``raw_text`` filled in for text
regions.

Pipeline inside one page:

    render (144 DPI)  →  Hiro-Layout regions and (optionally) MolDet molecules
                      →  merge R1/R2/R5 intra-detector + R3/R4 cross-model
                      →  column_sort reading order  →  layout-guided text OCR

One render per page is reused by every consumer — region detector, molecule
detector and text recognizer — so none of them disagree about geometry (the
fixed 2 px/pt mapping shared with ``LayoutSpan`` and ``SourceEvidence``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from mbforge.application.pipeline.layout.labels import TABLE, TEXT_REGION_TYPES
from mbforge.application.pipeline.layout.merge import merge
from mbforge.application.pipeline.layout.reading_order import (
    assign as assign_reading_order,
)
from mbforge.application.pipeline.layout.regions import (
    build_regions,
    molecule_regions,
    px_per_pt,
)
from mbforge.application.pipeline.layout.table_html import html_table_to_markdown
from mbforge.foundation.logger import get_logger

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
    read_tables: bool = False,
    cross_model: bool = True,
    params: dict[str, Any] | None = None,
) -> LayoutPage:
    """Detect, merge, order and (optionally) read one already-rendered page.

    ``image`` is HWC uint8 **RGB** at *zoom* px/pt. ``cross_model`` also runs
    MolDet on that same render, so the merge rules can re-type a figure region
    that is really one molecule (R3) and keep a multi-molecule figure as a
    container (R4). ``read_tables`` recognizes ``table`` region content with
    the local SLANet-1M backend (best-effort enrichment).
    """
    from mbforge.application.ports import get_runtime

    dpi = float(zoom) * 72.0
    scale = px_per_pt(dpi)
    page_size_px = (float(image.shape[1]), float(image.shape[0]))

    boxes = get_runtime().hiro_layout.detect_regions(image, detector, threshold=conf)
    regions, page_frame = build_regions(
        boxes,
        doc_id=doc_id,
        page=page_num,
        page_size_px=page_size_px,
        dpi=dpi,
    )
    molecules = (
        _detect_molecules(
            image,
            doc_id=doc_id,
            page=page_num,
            page_size_px=page_size_px,
            dpi=dpi,
        )
        if cross_model
        else []
    )
    regions, merge_stats = merge(
        regions,
        molecules,
        page_height_pt=page_frame["height_pt"],
        px_per_pt=scale,
        params=params,
    )
    # Reading order must be assigned once, on the final post-merge set.
    regions = assign_reading_order(regions, page_frame)

    text_stats = _fill_text(regions, image) if read_text else {"text_regions": 0}
    table_stats = _fill_tables(regions, image) if read_tables else {"table_regions": 0}

    return LayoutPage(
        page_num=page_num,
        width_pt=page_frame["width_pt"],
        height_pt=page_frame["height_pt"],
        dpi=dpi,
        regions=regions,
        stats={
            "detected": len(boxes),
            "molecules_detected": len(molecules),
            "regions": len(regions),
            **merge_stats,
            **text_stats,
            **table_stats,
        },
    )


def _detect_molecules(
    image: np.ndarray,
    *,
    doc_id: str,
    page: int,
    page_size_px: tuple[float, float],
    dpi: float,
) -> list[dict[str, Any]]:
    """MolDet's molecule boxes for one page, in the shape the merge rules read.

    MolDet runs **after** the region detector and never nested inside it:
    ``gpu_gate`` is a capacity-1 semaphore and each detector takes it for its
    own forward pass. Both work off the one page render, so their boxes share a
    coordinate space and can be compared directly.

    A failed detection degrades to no molecules. Detection is still the
    authoritative molecule source, so R3/R4 stay inert rather than failing a
    page whose layout is perfectly good.
    """
    from mbforge.application.ports import get_runtime

    try:
        result = get_runtime().moldet.detect_molecules(Image.fromarray(image))
    except Exception as exc:  # noqa: BLE001 — enrichment must never break a run
        logger.warning("Layout molecule detection failed: %s", exc)
        return []

    return molecule_regions(
        result.bboxes,
        doc_id=doc_id,
        page=page,
        page_size_px=page_size_px,
        dpi=dpi,
    )


def _fill_text(regions: list[dict[str, Any]], image: np.ndarray) -> dict[str, int]:
    """Recognize text inside text regions and store it on each region."""
    text_regions = [r for r in regions if str(r.get("type")) in TEXT_REGION_TYPES]
    if not text_regions:
        return {"text_regions": 0}

    from mbforge.application.ports import get_runtime

    boxes = [(str(r["region_id"]), r["bbox_px"]) for r in text_regions]
    try:
        recognized = get_runtime().ocr_page_text.read_text_in_boxes(image, boxes)
    except Exception as exc:  # noqa: BLE001 — enrichment must never break a run
        logger.warning("Layout text recognition failed: %s", exc)
        recognized = {}

    filled = 0
    for region in text_regions:
        text = (recognized.get(str(region["region_id"])) or "").strip()
        region["text"] = text
        filled += 1 if text else 0
    return {"text_regions": len(text_regions), "text_filled": filled}


def _crop_region(image: np.ndarray, bbox_px: Sequence[float]) -> Image.Image:
    """Crop one region from the rendered page by its px ``[x0, y0, x1, y1]`` bbox."""
    x0, y0, x1, y1 = (max(0, int(round(value))) for value in bbox_px)
    height, width = image.shape[:2]
    x0, y0 = min(x0, width - 1), min(y0, height - 1)
    x1, y1 = min(x1, width), min(y1, height)
    return Image.fromarray(image[y0:y1, x0:x1])


def _fill_tables(regions: list[dict[str, Any]], image: np.ndarray) -> dict[str, int]:
    """Recognize ``table`` region content with SLANet-1M and store it.

    Each table crop goes through the local table recognizer once. The raw
    HTML is kept on ``region["html"]`` and the Markdown pipe table on
    ``region["text"]``, so it flows into ``page_text`` / ``SourceEvidence``
    unchanged. Recognition is best-effort enrichment: a missing model or a
    failed inference leaves the region empty and never breaks the page.
    """
    table_regions = [r for r in regions if str(r.get("type")) == TABLE]
    if not table_regions:
        return {"table_regions": 0}

    from mbforge.application.ports import get_runtime

    filled = 0
    for region in table_regions:
        try:
            crop = _crop_region(image, region["bbox_px"])
            html = get_runtime().table_slanet.predict_table(crop)
        except Exception as exc:  # noqa: BLE001 — enrichment must never break a run
            logger.warning("Layout table recognition failed: %s", exc)
            continue
        html = (html or "").strip()
        if not html:
            continue
        markdown = html_table_to_markdown(html)
        if not markdown:
            continue
        region["html"] = html
        region["text"] = markdown
        filled += 1
    return {"table_regions": len(table_regions), "tables_filled": filled}


def parse_pdf_layout(
    pdf_path: str | Path,
    *,
    doc_id: str,
    zoom: float = DEFAULT_RENDER_ZOOM,
    detector: Any | None = None,
    conf: float = DEFAULT_CONF,
    read_text: bool = True,
    read_tables: bool = False,
    cross_model: bool = True,
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
                read_tables=read_tables,
                cross_model=cross_model,
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
    from mbforge.application.pipeline.layout.labels import kind_vocab

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

"""Read-only layout-guided text recognition for one stored PDF page.

The full Extract branch persists these regions as ``SourceEvidence``. This
module is the assistant-facing preview: render one page, run the same local
layout producer and OCR reader, then keep only the regions that intersect the
requested PDF-point rectangle. Nothing is written to the library.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.foundation.errors import ModelNotAvailableError, ValidationError
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.layout.parse import (
    DEFAULT_RENDER_ZOOM,
    parse_page_image,
    render_page_rgb,
)
from mbforge.service.ports import get_runtime
from mbforge.service.use_cases.documents import pdf_render as pdf_render_service

logger = get_logger(__name__)

MAX_BLOCKS = 100


def _overlaps(box: Sequence[float], region: Sequence[float]) -> bool:
    """Whether a PDF-point box intersects the requested region at all."""
    ix0 = max(float(box[0]), float(region[0]))
    iy0 = max(float(box[1]), float(region[1]))
    ix1 = min(float(box[2]), float(region[2]))
    iy1 = min(float(box[3]), float(region[3]))
    return ix1 > ix0 and iy1 > iy0


def _validate_region(region: Sequence[float] | None) -> None:
    if region is None:
        return
    if len(region) != 4:
        raise ValidationError("region needs four PDF-point values: x0, y0, x1, y1")
    x0, y0, x1, y1 = (float(value) for value in region)
    if x1 <= x0 or y1 <= y0:
        raise ValidationError("region must satisfy x0 < x1 and y0 < y1")


def select_text_blocks(
    regions: Sequence[dict[str, Any]],
    *,
    region: Sequence[float] | None = None,
    max_blocks: int = 50,
) -> tuple[list[dict[str, Any]], bool]:
    """Keep non-empty text/table regions intersecting *region* in reading order."""
    if not 1 <= max_blocks <= MAX_BLOCKS:
        raise ValidationError(f"max_blocks must be within 1-{MAX_BLOCKS}")
    _validate_region(region)

    matches: list[dict[str, Any]] = []
    for region_row in regions:
        text = str(region_row.get("text") or "").strip()
        if not text:
            continue
        bbox = [float(value) for value in region_row.get("bbox_pdf") or []]
        if len(bbox) != 4:
            continue
        if region is not None and not _overlaps(bbox, region):
            continue
        matches.append(
            {
                "region_id": str(region_row.get("region_id") or ""),
                "kind": str(region_row.get("label") or ""),
                "type": str(region_row.get("type") or ""),
                "bbox_pdf": bbox,
                "reading_order": int(region_row.get("reading_order") or 0),
                "text": text,
            }
        )
    return matches[:max_blocks], len(matches) > max_blocks


def ocr_page_region(
    pdf_path: str,
    *,
    doc_id: str,
    page: int,
    region: Sequence[float] | None = None,
    max_blocks: int = 50,
) -> dict[str, Any]:
    """Read the layout text blocks on one page, optionally one PDF region.

    The page is rendered once at the Extract contract's 144 DPI and parsed with
    the same local layout producer. ``region`` is applied in PDF points with a
    bottom-left origin; a block is kept when it intersects the region.
    """
    if page < 1:
        raise ValidationError("page must be >= 1")
    if not 1 <= max_blocks <= MAX_BLOCKS:
        raise ValidationError(f"max_blocks must be within 1-{MAX_BLOCKS}")
    _validate_region(region)

    detector = get_runtime().hiro_layout.get_hiro()
    if not detector.is_available():
        raise ModelNotAvailableError(
            "Hiro-Layout model is not available; cannot read page text"
        )

    document = pdf_render_service.open_pdf(pdf_path)
    try:
        if page > document.page_count:
            raise ValidationError(f"page must be within 1-{document.page_count}")
        pdf_page = document.load_page(page - 1)
        image = render_page_rgb(pdf_page, DEFAULT_RENDER_ZOOM)
        parsed = parse_page_image(
            image,
            doc_id=doc_id,
            page_num=page,
            zoom=DEFAULT_RENDER_ZOOM,
            detector=detector,
            cross_model=False,
        )
    finally:
        document.close()

    blocks, truncated = select_text_blocks(
        parsed.regions, region=region, max_blocks=max_blocks
    )
    return {
        "doc_id": doc_id,
        "page": page,
        "page_width_pts": round(parsed.width_pt, 2),
        "page_height_pts": round(parsed.height_pt, 2),
        "dpi": round(parsed.dpi, 2),
        "region": [float(value) for value in region] if region is not None else None,
        "count": len(blocks),
        "truncated": truncated,
        "text": "\n\n".join(block["text"] for block in blocks),
        "blocks": blocks,
    }


__all__ = ["MAX_BLOCKS", "ocr_page_region", "select_text_blocks"]

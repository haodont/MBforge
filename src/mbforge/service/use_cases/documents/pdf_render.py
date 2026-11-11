"""PDF page rendering service.

Shared PyMuPDF rendering primitives used by the viewer's base64 batch
endpoint, the molecule detection service's single-page rasterizer, and the
agent's page-image capability.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from mbforge.foundation.errors import ValidationError


def open_pdf(pdf_path: str):
    """Open a PDF with PyMuPDF (import deferred — pymupdf is heavy)."""
    import pymupdf  # PyMuPDF

    return pymupdf.open(pdf_path)


def page_matrix(dpi: float):
    """Return the pymupdf zoom matrix for *dpi* (72 dpi = 1x)."""
    import pymupdf

    return pymupdf.Matrix(dpi / 72, dpi / 72)


def render_page_pixmap(page, dpi: float, *, alpha: bool = False):
    """Rasterize a loaded pymupdf page at *dpi*."""
    return page.get_pixmap(matrix=page_matrix(dpi), alpha=alpha)


def render_pages_to_base64(
    pdf_path: str,
    page_indices: list[int] | None = None,
    dpi: int = 200,
) -> list[dict]:
    """Render PDF pages to base64 PNG payloads (sync)."""
    doc = open_pdf(pdf_path)
    pages_to_render = page_indices if page_indices else list(range(len(doc)))
    results = []
    for page_idx in pages_to_render:
        if page_idx < 0 or page_idx >= len(doc):
            continue
        page = doc[page_idx]
        pix = render_page_pixmap(page, dpi)
        img_bytes = pix.tobytes("png")
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        results.append(
            {
                "page": page_idx,
                "width": pix.width,
                "height": pix.height,
                "image_base64": img_b64,
            }
        )
    doc.close()
    return results


def render_page_image_base64(
    pdf_path: str,
    page_number: int,
    *,
    dpi: int = 144,
    region: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Render one 1-based page or one PDF-point region as a PNG payload.

    ``region`` uses the same bottom-left-origin PDF-point contract as
    ``SourceEvidence.bbox_pdf``. The long side is capped so a full page stays a
    reasonable image attachment.
    """
    if page_number < 1:
        raise ValidationError("page must be >= 1")
    if not 72 <= dpi <= 200:
        raise ValidationError("dpi must be within 72-200")
    if region is not None:
        if len(region) != 4:
            raise ValidationError("region needs four PDF-point values")
        if not (float(region[2]) > float(region[0])) or not (
            float(region[3]) > float(region[1])
        ):
            raise ValidationError("region must satisfy x0 < x1 and y0 < y1")

    doc = open_pdf(pdf_path)
    try:
        if page_number > doc.page_count:
            raise ValidationError(f"page must be within 1-{doc.page_count}")
        page = doc[page_number - 1]
        page_rect = page.rect
        width_pts = float(page_rect.width)
        height_pts = float(page_rect.height)

        clip = None
        if region is not None:
            x0, y0, x1, y1 = (float(value) for value in region)
            # SourceEvidence bboxes use a bottom-left origin; PyMuPDF clips use
            # the page's top-left origin.
            top = height_pts - y1
            bottom = height_pts - y0
            left = max(0.0, min(x0, width_pts))
            right = max(0.0, min(x1, width_pts))
            top = max(0.0, min(top, height_pts))
            bottom = max(0.0, min(bottom, height_pts))
            if right <= left or bottom <= top:
                raise ValidationError("region is outside the page")
            import pymupdf

            clip = pymupdf.Rect(left, top, right, bottom)

        scale = dpi / 72
        visible_width = (clip.width if clip is not None else width_pts) * scale
        visible_height = (clip.height if clip is not None else height_pts) * scale
        longest = max(visible_width, visible_height)
        max_side = 2200
        if longest > max_side:
            scale *= max_side / longest

        import pymupdf

        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            clip=clip,
            alpha=False,
        )
        png = pix.tobytes("png")
        return {
            "page": page_number,
            "page_width_pts": width_pts,
            "page_height_pts": height_pts,
            "dpi": dpi,
            "region": [float(value) for value in region] if region else None,
            "width": pix.width,
            "height": pix.height,
            "image_base64": base64.b64encode(png).decode("ascii"),
            "mime_type": "image/png",
        }
    finally:
        doc.close()

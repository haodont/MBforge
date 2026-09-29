"""PDF page rendering service.

Shared PyMuPDF rendering primitives used by the viewer's base64 batch
endpoint and by the molecule detection service's single-page rasterizer.
"""

from __future__ import annotations

import base64


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

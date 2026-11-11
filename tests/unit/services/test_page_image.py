"""Function under test: ``render_page_image_base64``.

The page-image capability must return a real PNG and honour the same
bottom-left PDF-point region contract used by evidence boxes. A wrong crop is
silent and makes the model reason about the wrong part of the page.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from mbforge.foundation.errors import ValidationError
from mbforge.service.use_cases.documents.pdf_render import render_page_image_base64


def test_render_page_image_returns_png_and_honours_region(sample_pdf: Path) -> None:
    full = render_page_image_base64(str(sample_pdf), 1, dpi=144)
    raw = base64.b64decode(full["image_base64"])

    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert full["page"] == 1
    assert full["page_width_pts"] == pytest.approx(612.0)
    assert full["page_height_pts"] == pytest.approx(792.0)
    assert full["width"] > 0 and full["height"] > 0

    region = render_page_image_base64(
        str(sample_pdf), 1, dpi=144, region=[72, 72, 300, 300]
    )
    assert region["region"] == pytest.approx([72.0, 72.0, 300.0, 300.0])
    assert region["width"] < full["width"]
    assert region["height"] < full["height"]

    with pytest.raises(ValidationError):
        render_page_image_base64(str(sample_pdf), 1, dpi=144, region=[300, 300, 72, 72])
    with pytest.raises(ValidationError):
        render_page_image_base64(str(sample_pdf), 99, dpi=144)

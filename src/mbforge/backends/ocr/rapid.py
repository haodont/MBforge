"""Local RapidOCR full-page reads — offline line recovery for pages.

The cloud OCR chain (``chain.py``) targets whole pages through remote
layout services; when such a backend drops a text line, the pixels are
still in the source PDF. This module runs RapidOCR (ONNX, CPU — models
ship inside the ``rapidocr-onnxruntime`` wheel) directly on a rendered
page image to re-read those lines locally.

Deliberately minimal and dependency-free beyond the engine: callers own
the domain filtering for any future offline OCR use.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from PIL import Image

from ...utils.logger import get_logger

logger = get_logger(__name__)

_ENGINE = None


class OcrRead(NamedTuple):
    """One detected text region: text, confidence, tight pixel box."""

    text: str
    confidence: float
    box: tuple[int, int, int, int]


class OcrLine(NamedTuple):
    """Reads joined into one visual line (same baseline band)."""

    text: str
    confidence: float
    box: tuple[int, int, int, int]


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _tight_box(points) -> tuple[int, int, int, int]:
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def read_lines(image: Image.Image) -> list[OcrRead]:
    """OCR *image*; return reads sorted top-to-bottom, left-to-right.

    Empty list when the engine fails — local recovery is best-effort
    enrichment and must never break its caller.
    """
    try:
        result, _ = _engine()(np.asarray(image.convert("RGB")))
    except Exception as exc:
        logger.warning("RapidOCR page read failed: %s", exc)
        return []
    reads = [
        OcrRead(str(text).strip(), float(conf), _tight_box(points))
        for points, text, conf in (result or [])
        if str(text or "").strip()
    ]
    reads.sort(key=lambda r: (r.box[1], r.box[0]))
    return reads


def assemble_lines(reads: list[OcrRead]) -> list[OcrLine]:
    """Join reads whose vertical bands overlap into visual text lines.

    Detectors often split one printed line into several boxes (``实施例``
    / ``10：`` / the title tail); the heading regexes downstream need the
    whole line in one string. Reads are merged per baseline band —
    sorted by x within the band, concatenated without separators (CJK
    patent text; the spacing tolerance lives in the regex). Confidence
    is the band minimum; the box is the band union.
    """
    lines: list[OcrLine] = []
    band: list[OcrRead] = []
    band_top = band_bottom = 0

    def _flush() -> None:
        if not band:
            return
        ordered = sorted(band, key=lambda r: r.box[0])
        text = "".join(r.text for r in ordered)
        conf = min(r.confidence for r in ordered)
        box = (
            min(r.box[0] for r in ordered),
            min(r.box[1] for r in ordered),
            max(r.box[2] for r in ordered),
            max(r.box[3] for r in ordered),
        )
        lines.append(OcrLine(text, conf, box))

    for read in reads:
        top, bottom = read.box[1], read.box[3]
        height = max(1, bottom - top)
        if band and min(bottom, band_bottom) - max(top, band_top) < 0.5 * height:
            _flush()
            band = []
        if not band:
            band_top, band_bottom = top, bottom
        else:
            band_top, band_bottom = min(band_top, top), max(band_bottom, bottom)
        band.append(read)
    _flush()
    return lines

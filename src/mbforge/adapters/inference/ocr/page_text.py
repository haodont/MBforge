"""Layout-guided page text recognition (local RapidOCR).

Reads the text inside the layout detector's ``text`` regions and returns the
joined ``raw_text`` per region. This is the producer of ``SourceEvidence.raw_text``
for layout-derived text regions, without which those regions cannot be
constructed as evidence at all (``SourceEvidence`` requires ``raw_text`` or
``coref`` to be non-empty).

Why the page is not simply OCR'd as a whole: on the source project's sample,
**38.2% of raw page-wide OCR lines landed inside structure diagrams / figures**
(49.1% on figure-heavy pages) — substituent symbols, reagent names, bond
labels. Those are pure noise for a text region. Detecting on the whole page and
then keeping only lines whose center falls inside a layout text region removes
them.

Why not OCR each block separately either: RapidOCR's detector is configured with
``limit_side_len=736, limit_type=min``, so a 939×174 text block gets upscaled
~4.2x — measured 1712 ms/page, slower than the whole page. Detecting once per
page and batching the recognition is the fast path (fixed overhead paid once).

Like :mod:`mbforge.adapters.inference.ocr.crop_labels`, this is **enrichment**: any
failure degrades to an empty result and never raises.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

import numpy as np

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

#: RapidOCR model selection (the source project's working point).
DEFAULT_OCR_VERSION = "PPOCRV6"
DEFAULT_MODEL_TYPE = "SMALL"

#: A detected line whose center falls inside a layout box is attributed to it.
_MIN_BOX_SIDE_PX = 4

_thread_engines = threading.local()

_CJK_MIN = 0x2E80  # CJK radicals and up; covers CJK text and full-width punctuation
_NO_SPACE_AFTER = set("-([{/")  # don't add a space after these


def _is_cjk(ch: str) -> bool:
    return ord(ch) >= _CJK_MIN


def _needs_space(prev: str, nxt: str) -> bool:
    """Whether a line break between *prev* and *nxt* should become a space.

    - either side is CJK (incl. full-width punctuation) → no space
    - previous line ends with ``-([{/`` → no space (hyphenation, openers)
    - otherwise → space (English prose)

    The CJK test is deliberate: an "both sides are ASCII alnum" rule misses
    spaces at *punctuation* breaks and produces ``redness,swelling`` /
    ``M2),comparisons`` / ``;MacDonald``.
    """
    if _is_cjk(prev) or _is_cjk(nxt):
        return False
    return prev not in _NO_SPACE_AFTER


def join_lines(texts: Sequence[str]) -> str:
    """Join recognized lines into one ``raw_text``, handling CJK/Latin wrapping."""
    out = ""
    for text in texts:
        if not text:
            continue
        if out and _needs_space(out[-1], text[0]):
            out += " "
        out += text
    return out


def _create_engine():
    """Create the RapidOCR torch/CUDA engine, or ``None`` when unavailable.

    Direction classification is disabled on purpose: it rotates/mirrors crops,
    which would break the fixed 2 px/pt coordinate mapping between the layout
    regions and the recognized lines.
    """
    try:
        from rapidocr import EngineType, RapidOCR
        from rapidocr.utils.typings import ModelType, OCRVersion

        return RapidOCR(
            params={
                "Global.log_level": "error",
                "Global.use_cls": False,
                "Det.engine_type": EngineType.TORCH,
                "Det.ocr_version": getattr(OCRVersion, DEFAULT_OCR_VERSION),
                "Det.model_type": getattr(ModelType, DEFAULT_MODEL_TYPE),
                "Rec.engine_type": EngineType.TORCH,
                "Rec.ocr_version": getattr(OCRVersion, DEFAULT_OCR_VERSION),
                "Rec.model_type": getattr(ModelType, DEFAULT_MODEL_TYPE),
                "EngineConfig.torch.use_cuda": True,
            }
        )
    except Exception as exc:  # noqa: BLE001 — enrichment: never fail the caller
        logger.warning("page text OCR engine unavailable (%s)", exc)
        return None


def _get_engine():
    """Return this thread's lazy RapidOCR engine (per-thread, reused)."""
    engine = getattr(_thread_engines, "engine", None)
    if engine is None:
        engine = _create_engine()
        _thread_engines.engine = engine
    return engine


def _clear_engines() -> None:
    """Drop the cached per-thread engines (unload hook)."""
    _thread_engines.engine = None


def _to_bgr(image: np.ndarray) -> np.ndarray:
    """RapidOCR's OpenCV pipeline expects BGR; page renders arrive as RGB."""
    if image.ndim == 2:
        return np.stack([image] * 3, -1)
    return np.ascontiguousarray(image[:, :, :3][:, :, ::-1])


def read_text_in_boxes(
    image: np.ndarray,
    boxes: Sequence[tuple[str, Sequence[float]]],
) -> dict[str, str]:
    """Recognize the text inside layout boxes and join it per region.

    Args:
        image: Page render, HWC uint8 **RGB** (the pipeline's convention).
        boxes: ``(region_id, (x0, y0, x1, y1))`` in **image pixels** (top-left).

    Returns:
        ``{region_id: raw_text}`` for regions with at least one recognized line.
        Empty (never raising) when the engine is unavailable or nothing matched.
    """
    if not boxes or image is None or image.size == 0:
        return {}

    engine = _get_engine()
    if engine is None:
        return {}

    try:
        import numpy as _np
        from rapidocr.utils.process_img import map_boxes_to_original
    except Exception as exc:  # noqa: BLE001 — rapidocr internals moved
        logger.warning("page text OCR internals unavailable (%s)", exc)
        return {}

    arr_bgr = _to_bgr(image)
    page_h, page_w = arr_bgr.shape[:2]

    try:
        from mbforge.adapters.runtime.process import gpu_gate

        with gpu_gate():
            prepared, operations = engine.preprocess_img(arr_bgr)
            crops, detection = engine.detect_and_crop(prepared, operations)
            if not crops:
                return {}
            line_boxes = map_boxes_to_original(
                detection.boxes, operations, page_h, page_w
            )
            recognized = engine.recognize_txt(crops)
    except Exception as exc:  # noqa: BLE001 — enrichment: degrade to empty
        logger.warning("page text OCR failed (%s)", exc)
        return {}

    texts = list(getattr(recognized, "txts", None) or [])

    per_region: dict[str, list[tuple[float, float, str]]] = {}
    # Lengths come from RapidOCR internals; tolerate a mismatch rather than
    # aborting a whole page of enrichment over one stray entry.
    for line_box, text in zip(line_boxes, texts, strict=False):
        if not text:
            continue
        box = _np.asarray(line_box, dtype=float)
        if box.size == 0:
            continue
        center_x = (float(box[:, 0].min()) + float(box[:, 0].max())) / 2
        center_y = (float(box[:, 1].min()) + float(box[:, 1].max())) / 2
        region_id = _region_for_point(boxes, center_x, center_y)
        if region_id is None:
            continue
        # Raster order within the region (top-to-bottom, then left-to-right).
        per_region.setdefault(region_id, []).append(
            (float(box[:, 1].min()), float(box[:, 0].min()), str(text))
        )

    return {
        region_id: join_lines([text for _, _, text in sorted(lines)])
        for region_id, lines in per_region.items()
    }


def _region_for_point(
    boxes: Sequence[tuple[str, Sequence[float]]], x: float, y: float
) -> str | None:
    """Return the region id whose box contains ``(x, y)`` (first match wins)."""
    for region_id, box in boxes:
        x0, y0, x1, y1 = (float(value) for value in box)
        if x0 <= x <= x1 and y0 <= y <= y1:
            return region_id
    return None


__all__ = [
    "DEFAULT_MODEL_TYPE",
    "DEFAULT_OCR_VERSION",
    "join_lines",
    "read_text_in_boxes",
]

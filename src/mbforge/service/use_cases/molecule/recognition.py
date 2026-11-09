"""Read-side molecule recognition for the assistant's tool surface.

Renders one stored PDF page and returns the structures the local MolDetv2
detector + MolParser recognizer find on it. Strictly read-only: nothing is
persisted and no model output is normalized away, so the agent can cite what
the detectors actually saw.

Coordinates are returned twice on purpose:

- ``bbox_px`` — what the detector saw (top-left origin, render pixels);
- ``bbox_pdf`` — PDF points with a **bottom-left origin**, the same convention
  the document overlay and ``source_evidence`` rows use, so a region argument
  and a cited box round-trip without another y-axis flip.

``region`` is applied in PDF points (bottom-left origin): a structure is kept
when its box intersects the region, which lets the model ask about one table
cell instead of the whole page.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from mbforge.foundation.errors import ValidationError
from mbforge.foundation.logger import get_logger
from mbforge.service.ports import get_runtime

logger = get_logger(__name__)

#: MolDetv2 is trained at 200 DPI; the same resolution the Extract stage uses.
DETECT_DPI = 200.0
#: Below this the detector mostly reports table rules and ring fragments.
MIN_CONFIDENCE = 0.7
MAX_MOLECULES = 20
#: How far around a detected box the label OCR looks for a printed designation.
LABEL_PAD = 0.2


def _render_page(
    pdf_path: str, page: int, dpi: float
) -> tuple[Any, int, int, float, float]:
    """Render one 1-based page to a PIL image plus its pixel/point sizes."""
    import numpy as np
    from PIL import Image

    from mbforge.service.use_cases.documents import pdf_render as pdf_render_service

    document = pdf_render_service.open_pdf(pdf_path)
    try:
        if page < 1 or page > document.page_count:
            raise ValidationError(f"page must be within 1-{document.page_count}")
        pdf_page = document.load_page(page - 1)
        width_pts = float(pdf_page.rect.width)
        height_pts = float(pdf_page.rect.height)
        pix = pdf_render_service.render_page_pixmap(pdf_page, dpi, alpha=False)
        array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        return Image.fromarray(array), pix.width, pix.height, width_pts, height_pts
    finally:
        document.close()


def _to_pdf_box(
    box_px: Sequence[float], img_w: int, img_h: int, page_w: float, page_h: float
) -> list[float]:
    """Pixel box (top-left origin) → PDF points (bottom-left origin)."""
    scale_x = page_w / img_w if img_w else 0.0
    scale_y = page_h / img_h if img_h else 0.0
    x0, y0, x1, y1 = (float(value) for value in box_px)
    return [
        round(x0 * scale_x, 2),
        round(page_h - y1 * scale_y, 2),
        round(x1 * scale_x, 2),
        round(page_h - y0 * scale_y, 2),
    ]


def _overlaps(box: Sequence[float], region: Sequence[float]) -> bool:
    """Whether a PDF-point box intersects the requested region at all."""
    ix0 = max(float(box[0]), float(region[0]))
    iy0 = max(float(box[1]), float(region[1]))
    ix1 = min(float(box[2]), float(region[2]))
    iy1 = min(float(box[3]), float(region[3]))
    return ix1 > ix0 and iy1 > iy0


def _crop(image: Any, box_px: Sequence[float], pad_px: int = 2):
    """Crop a detected box with a small pad, clipped to the image."""
    x0 = max(0, int(math.floor(box_px[0])) - pad_px)
    y0 = max(0, int(math.floor(box_px[1])) - pad_px)
    x1 = min(image.width, int(math.ceil(box_px[2])) + pad_px)
    y1 = min(image.height, int(math.ceil(box_px[3])) + pad_px)
    if x1 <= x0 or y1 <= y0:
        return None
    return image.crop((x0, y0, x1, y1)).convert("L")


def _padded_crop(image: Any, box_px: Sequence[float]):
    """Crop around a box by ``LABEL_PAD`` so printed designations are included."""
    width = box_px[2] - box_px[0]
    height = box_px[3] - box_px[1]
    pad_x = width * LABEL_PAD
    pad_y = height * LABEL_PAD
    x0 = max(0, int(math.floor(box_px[0] - pad_x)))
    y0 = max(0, int(math.floor(box_px[1] - pad_y)))
    x1 = min(image.width, int(math.ceil(box_px[2] + pad_x)))
    y1 = min(image.height, int(math.ceil(box_px[3] + pad_y)))
    if x1 <= x0 or y1 <= y0:
        return None
    return image.crop((x0, y0, x1, y1))


def _labels_for(image: Any, box_px: Sequence[float]) -> list[str]:
    """OCR the padded crop for a printed compound designation; best effort."""
    crop = _padded_crop(image, box_px)
    if crop is None:
        return []
    try:
        reader = get_runtime().ocr_label_reader.get_label_reader()
        reads = reader.read(crop)
    except Exception as exc:  # noqa: BLE001 - labels are enrichment only
        logger.warning("label OCR failed: %s", exc)
        return []
    labels: list[str] = []
    for read in reads:
        text = str(read[0]).strip()
        if text and text not in labels:
            labels.append(text)
    return labels[:8]


def recognize_page_molecules(
    pdf_path: str,
    *,
    page: int,
    region: Sequence[float] | None = None,
    max_molecules: int = MAX_MOLECULES,
    mol_conf_threshold: float = MIN_CONFIDENCE,
    dpi: float = DETECT_DPI,
) -> dict[str, Any]:
    """Detect and recognize the structures drawn on one PDF page.

    Args:
        pdf_path: Absolute path to the stored PDF (resolved by the router).
        page: 1-based page number.
        region: Optional ``[x0, y0, x1, y1]`` in PDF points, bottom-left origin.
        max_molecules: Cap on recognized structures; the response says when it
            was hit instead of silently dropping the rest.
        mol_conf_threshold: Detector confidence gate.
        dpi: Render resolution; 200 is MolDetv2's training resolution.

    Returns:
        ``{page, page_width_pts, page_height_pts, dpi, region, count,
        truncated, molecules: [{index, bbox_px, bbox_pdf, score, smiles,
        esmiles, labels}]}``
    """
    if page < 1:
        raise ValidationError("page must be >= 1")
    if not 1 <= max_molecules <= MAX_MOLECULES:
        raise ValidationError(f"max_molecules must be within 1-{MAX_MOLECULES}")
    if region is not None and len(region) != 4:
        raise ValidationError("region needs four PDF-point values: x0, y0, x1, y1")

    image, img_w, img_h, page_w, page_h = _render_page(pdf_path, page, dpi)
    result = get_runtime().moldet.detect_molecules(
        image, mol_conf_threshold=mol_conf_threshold
    )

    boxes_px: list[tuple[float, float, float, float, float]] = []
    for candidate in result.bboxes:
        x0, y0, x1, y1 = (float(value) for value in candidate.bbox)
        px = [x0 * img_w, y0 * img_h, x1 * img_w, y1 * img_h]
        pdf_box = _to_pdf_box(px, img_w, img_h, page_w, page_h)
        if region is not None and not _overlaps(pdf_box, region):
            continue
        boxes_px.append((px[0], px[1], px[2], px[3], float(candidate.score)))

    total = len(boxes_px)
    selected = boxes_px[:max_molecules]
    if selected:
        get_runtime().molparser.load()

    molecules: list[dict[str, Any]] = []
    for index, (x0, y0, x1, y1, score) in enumerate(selected):
        crop = _crop(image, (x0, y0, x1, y1))
        smiles = ""
        esmiles = ""
        if crop is not None:
            try:
                recognition = get_runtime().molparser.predict(crop)
                smiles = (recognition.smiles or "").strip()
                esmiles = (recognition.esmiles or "").strip()
            except Exception as exc:  # noqa: BLE001 - one bad crop must not fail the page
                logger.warning(
                    "MolParser failed on page %s box %s: %s", page, index, exc
                )
        molecules.append(
            {
                "index": index,
                "bbox_px": [round(value, 1) for value in (x0, y0, x1, y1)],
                "bbox_pdf": _to_pdf_box((x0, y0, x1, y1), img_w, img_h, page_w, page_h),
                "score": round(score, 3),
                "smiles": smiles,
                "esmiles": esmiles,
                "labels": _labels_for(image, (x0, y0, x1, y1)),
            }
        )

    return {
        "page": page,
        "page_width_pts": round(page_w, 2),
        "page_height_pts": round(page_h, 2),
        "dpi": dpi,
        "region": [float(value) for value in region] if region is not None else None,
        "count": len(molecules),
        "truncated": total > len(selected),
        "molecules": molecules,
    }

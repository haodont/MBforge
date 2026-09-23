"""Region model and px → PDF coordinate conversion for the layout pipeline.

A region is a plain dict (the same shape the branch artifact carries):

    region_id, doc_id, page, kind, type, label, cls_id, score, source,
    reading_order, bbox_px, bbox_pdf

``kind`` is the detector's original label (``chem`` / ``figcx`` / ``mnote`` …)
and is deliberately kept verbatim — MBForge evidence kinds are an open label
space, so no detection detail is lost. ``type`` is the product-level RegionType.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.application.pipeline.layout.labels import category_of_label, region_type_of

#: Contract render resolution: 144 DPI = 2 px/pt (matches ``_OCR_RENDER_PX_PER_PT``).
DEFAULT_RENDER_DPI = 144.0


def px_per_pt(dpi: float = DEFAULT_RENDER_DPI) -> float:
    """Pixels per PDF point at *dpi*."""
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    return float(dpi) / 72.0


def px_box_to_pdf(
    box_px: Sequence[float], page_height_pt: float, scale: float
) -> tuple[float, float, float, float]:
    """Image pixels (top-left origin, y down) → PDF points (bottom-left, y up).

    ⚠️ ``y0``/``y1`` must be swapped. Applying ``page_height_pt - y/scale``
    coordinate-by-coordinate yields an inverted box and raises nothing.
    """
    x0, y0, x1, y1 = (float(value) for value in box_px)
    return (
        x0 / scale,
        page_height_pt - y1 / scale,
        x1 / scale,
        page_height_pt - y0 / scale,
    )


def build_regions(
    boxes: Sequence[Any],
    *,
    doc_id: str,
    page: int,
    page_size_px: tuple[float, float],
    dpi: float = DEFAULT_RENDER_DPI,
    source: str = "layout_hiro",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assemble raw detector boxes into regions plus their page frame.

    Args:
        boxes: Detector output items (objects exposing ``cls_id`` / ``label`` /
            ``bbox_px`` / ``score``) in **image pixels, top-left origin**.
        page_size_px: ``(width_px, height_px)`` of the rendered page.

    Returns:
        ``(regions, page)`` where ``page`` carries the px/pt frame used by every
        downstream conversion.
    """
    width_px, height_px = (float(value) for value in page_size_px)
    scale = px_per_pt(dpi)
    page_height_pt = height_px / scale
    page_width_pt = width_px / scale

    regions: list[dict[str, Any]] = []
    for seq, box in enumerate(boxes):
        label = str(getattr(box, "label", ""))
        region_type = region_type_of(label)
        bbox_px = tuple(float(value) for value in box.bbox_px)
        regions.append(
            {
                "region_id": f"{doc_id}-{page}-{region_type}-{seq}",
                "doc_id": doc_id,
                "page": page,
                "kind": label,
                "type": region_type,
                "label": label,
                "cls_id": int(getattr(box, "cls_id", -1)),
                "score": float(getattr(box, "score", 0.0)),
                "source": source,
                # Detector output order is not a reading order (Hiro does not
                # emit one); reading_order.assign() overwrites this.
                "reading_order": seq,
                "bbox_px": [round(value, 2) for value in bbox_px],
                "bbox_pdf": [
                    round(value, 2)
                    for value in px_box_to_pdf(bbox_px, page_height_pt, scale)
                ],
            }
        )

    page_frame = {
        "width_px": width_px,
        "height_px": height_px,
        "width_pt": round(page_width_pt, 2),
        "height_pt": round(page_height_pt, 2),
        "dpi": dpi,
        "px_per_pt": scale,
    }
    return regions, page_frame


def region_category(region: dict[str, Any]) -> str:
    """Evidence category of one region."""
    return category_of_label(str(region.get("label", "")))


def molecule_regions(
    molecules: Sequence[Any],
    *,
    doc_id: str,
    page: int,
    page_size_px: tuple[float, float],
    dpi: float = DEFAULT_RENDER_DPI,
    source: str = "molecule_det",
) -> list[dict[str, Any]]:
    """Assemble MolDet molecule boxes into regions of the layout shape.

    MolDet emits **normalized [0, 1]** boxes (``MoleculeBbox.bbox``, top-left
    origin); they are scaled to the rendered page pixels here and converted to
    PDF points with the same helper the Hiro regions use, so both models land in
    one coordinate space and can be merged directly.

    Args:
        molecules: Objects exposing ``bbox`` (normalized ``x0,y0,x1,y1``) and
            ``score``, or dicts with the same keys.
    """
    width_px, height_px = (float(value) for value in page_size_px)
    scale = px_per_pt(dpi)
    page_height_pt = height_px / scale

    regions: list[dict[str, Any]] = []
    for seq, molecule in enumerate(molecules):
        normalized = (
            molecule["bbox"]
            if isinstance(molecule, dict)
            else getattr(molecule, "bbox", ())
        )
        score = (
            molecule.get("score", 0.0)
            if isinstance(molecule, dict)
            else getattr(molecule, "score", 0.0)
        )
        if len(normalized) != 4:
            continue
        x0, y0, x1, y1 = (float(value) for value in normalized)
        bbox_px = (x0 * width_px, y0 * height_px, x1 * width_px, y1 * height_px)
        regions.append(
            {
                "region_id": f"{doc_id}-{page}-molecule-{seq}",
                "doc_id": doc_id,
                "page": page,
                "kind": "molecule",
                "type": "molecule",
                "label": "molecule",
                "cls_id": -1,
                "score": float(score),
                "source": source,
                "reading_order": seq,
                "bbox_px": [round(value, 2) for value in bbox_px],
                "bbox_pdf": [
                    round(value, 2)
                    for value in px_box_to_pdf(bbox_px, page_height_pt, scale)
                ],
            }
        )
    return regions


def is_text_region(region: dict[str, Any]) -> bool:
    """Whether this region carries running text (i.e. should be OCR'd)."""
    from mbforge.application.pipeline.layout.labels import TEXT_REGION_TYPES

    return str(region.get("type", "")) in TEXT_REGION_TYPES


__all__ = [
    "DEFAULT_RENDER_DPI",
    "build_regions",
    "is_text_region",
    "molecule_regions",
    "px_box_to_pdf",
    "px_per_pt",
    "region_category",
]

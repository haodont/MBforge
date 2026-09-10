"""Heavy pipeline for MolDetv2 + MolParser PDF page extraction.

Owns the synchronous PDF render, molecule detection, per-crop MolParser
recognition, and pixel-to-point coordinate conversion consumed by the
``/api/v1/moldet/extract-pdf-page`` endpoint.
"""

from __future__ import annotations

from typing import Any

from mbforge.backends.moldet_v2_ft import detect_molecules, to_api_dict
from mbforge.utils.errors import ValidationError
from mbforge.utils.logger import get_logger

logger = get_logger(__name__)


def _render_pdf_page_sync(pdf_path: str, page_num: int, dpi: float) -> dict[str, Any]:
    """Render one PDF page to a PIL image and return its dims.

    Returns dict with keys: image (PIL.Image), img_w, img_h,
    page_w_pts, page_h_pts. Closes the fitz doc before returning.
    """
    import numpy as np
    from PIL import Image

    from ..documents import pdf_render as pdf_render_service

    doc = pdf_render_service.open_pdf(pdf_path)
    try:
        page_index = int(page_num) - 1
        if page_index < 0 or page_index >= doc.page_count:
            raise ValidationError(f"Page {page_num} out of range (1-{doc.page_count})")
        page = doc.load_page(page_index)
        page_w_pts = page.rect.width
        page_h_pts = page.rect.height

        pix = pdf_render_service.render_page_pixmap(page, dpi, alpha=False)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        image = Image.fromarray(img_array)
        return {
            "image": image,
            "img_w": pix.width,
            "img_h": pix.height,
            "page_w_pts": page_w_pts,
            "page_h_pts": page_h_pts,
        }
    finally:
        doc.close()


def _molparser_for_crop_sync(
    image, x1: int, y1: int, x2: int, y2: int
) -> tuple[str, str]:
    """Crop a bbox from image and run MolParser to SMILES.

    Returns ``(smiles, esmiles)`` — Layer-1 SMILES (RDKit parseable) and full
    Layer-2 E-SMILES. Empty strings on failure.
    """
    from mbforge.backends import molparser

    px1, py1 = max(0, int(x1)), max(0, int(y1))
    px2, py2 = min(image.width, int(x2)), min(image.height, int(y2))
    if px2 <= px1 or py2 <= py1:
        return "", ""
    crop = image.crop((px1, py1, px2, py2)).convert("L")
    try:
        result = molparser.predict(crop)
        smiles = result.smiles or ""
        return smiles, result.esmiles or ""
    except Exception as e:  # noqa: BLE001 - MolParser is best-effort
        logger.warning(
            "MolParser failed on crop (%s,%s,%s,%s): %s",
            px1,
            py1,
            px2,
            py2,
            e,
        )
        return "", ""


def extract_pdf_page(
    pdf_path: str,
    page_num: int,
    dpi: float,
    mol_conf_threshold: float,
) -> dict[str, Any]:
    """Full PDF page pipeline: render -> FT detect -> MolParser recognition.

    This is the synchronous body of ``/api/v1/moldet/extract-pdf-page``;
    the router wraps it in ``asyncio.to_thread`` to keep it off the
    event loop.
    """
    # 1. Render PDF page (sync fitz call)
    page_info = _render_pdf_page_sync(pdf_path, page_num, dpi)
    image = page_info["image"]
    img_w = page_info["img_w"]
    img_h = page_info["img_h"]
    page_w_pts = page_info["page_w_pts"]
    page_h_pts = page_info["page_h_pts"]

    # 2. FT detection
    result = detect_molecules(image, mol_conf_threshold=mol_conf_threshold)

    # Molecule bboxes (normalized) -> pixel coords.
    mol_boxes_px: list[tuple[int, int, int, int, float]] = []
    for cb in result.bboxes:
        x1 = int(round(cb.bbox[0] * img_w))
        y1 = int(round(cb.bbox[1] * img_h))
        x2 = int(round(cb.bbox[2] * img_w))
        y2 = int(round(cb.bbox[3] * img_h))
        mol_boxes_px.append((x1, y1, x2, y2, cb.score))
    api_dict = to_api_dict(result)
    if not mol_boxes_px:
        logger.info(
            "FT detector found no molecules on page %s of %s",
            page_num,
            pdf_path,
        )
        return {
            "page_num": int(page_num),
            "width": img_w,
            "height": img_h,
            "page_w_pts": page_w_pts,
            "page_h_pts": page_h_pts,
            "dpi": dpi,
            "molecules": [],
            "bboxes": api_dict["bboxes"],
            "count": 0,
        }

    # 3. MolParser: one recognition per mol bbox
    from mbforge.backends import molparser

    molparser.load()
    smiles_results = [
        _molparser_for_crop_sync(image, x1, y1, x2, y2)
        for x1, y1, x2, y2, _ in mol_boxes_px
    ]

    # 4. Assemble results - convert pixel -> PDF points (lower-left origin)
    scale_x = page_w_pts / img_w if img_w > 0 else 0
    scale_y = page_h_pts / img_h if img_h > 0 else 0

    molecules = []
    for i, (px1, py1, px2, py2, conf) in enumerate(mol_boxes_px):
        smi, esmi = smiles_results[i]
        molecules.append(
            {
                "index": i,
                "bbox": {
                    "x1": round(px1 * scale_x, 2),
                    "y1": round(page_h_pts - py2 * scale_y, 2),
                    "x2": round(px2 * scale_x, 2),
                    "y2": round(page_h_pts - py1 * scale_y, 2),
                },
                "confidence": round(conf, 4),
                "smiles": smi,
                "esmiles": esmi,
                "context_text": "",
            }
        )

    return {
        "page_num": int(page_num),
        "width": img_w,
        "height": img_h,
        "page_w_pts": page_w_pts,
        "page_h_pts": page_h_pts,
        "dpi": dpi,
        "molecules": molecules,
        "bboxes": api_dict["bboxes"],
        "count": len(molecules),
    }

"""Fold a masked table's molecule tokens back to their printed labels.

The layout producer blanks a structure drawing inside a table cell before cell
OCR and leaves a ``[MOL:n]`` token in that cell, which keeps the molecule's
row/column position. The molecule pass reads the printed compound number off the
same crop. This module is the one place that joins the two: it rewrites the
table region's Markdown before evidence is minted, leaving the token in place
when no label was read rather than inventing one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.domain.types import ExtractionResult


def label_for_cell(bbox: Sequence[float], results: Sequence[ExtractionResult]) -> str:
    """The printed label of the molecule result that occupies *bbox*, if any."""
    if len(bbox) != 4:
        return ""
    best_label = ""
    best_area = 0.0
    for result in results:
        candidate = result.bbox_pdf
        if candidate is None or len(candidate) != 4:
            continue
        ix0 = max(float(bbox[0]), float(candidate[0]))
        iy0 = max(float(bbox[1]), float(candidate[1]))
        ix1 = min(float(bbox[2]), float(candidate[2]))
        iy1 = min(float(bbox[3]), float(candidate[3]))
        area = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        if area <= best_area:
            continue
        label = (result.name or "").strip()
        if not label:
            labels = (result.properties or {}).get("ocr_labels") or []
            label = str(labels[0]).strip() if labels else ""
        if label:
            best_label, best_area = label, area
    return best_label


def resolve_table_molecule_tokens(
    pages: Sequence[Any], results: Sequence[ExtractionResult]
) -> None:
    """Replace table-cell ``[MOL:n]`` placeholders with the printed label.

    The layout producer masks a structure drawing before cell OCR, so the cell
    keeps a placeholder instead of the printed compound number. The molecule
    pass reads that number off the crop; folding it back here keeps the cell's
    row/column position while making the table read naturally. A molecule with
    no readable label keeps its token.
    """
    by_page: dict[int, list[ExtractionResult]] = {}
    for result in results:
        if result.page_idx is None or result.bbox_pdf is None:
            continue
        by_page.setdefault(result.page_idx + 1, []).append(result)
    for page in pages:
        candidates = by_page.get(page.page_num) or []
        if not candidates:
            continue
        for region in page.regions:
            cells = region.get("molecule_cells") or []
            text = str(region.get("text") or "")
            if not cells or not text:
                continue
            for cell in cells:
                token = str(cell.get("token") or "")
                if not token or token not in text:
                    continue
                label = label_for_cell(cell.get("bbox_pdf") or [], candidates)
                if label:
                    text = text.replace(token, label)
            region["text"] = text


__all__ = ["label_for_cell", "resolve_table_molecule_tokens"]

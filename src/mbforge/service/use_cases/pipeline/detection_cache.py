"""Detection cache service — ``molecule_detections`` table access.

All reads and writes for the detection cache (FE surface for read / clear /
stats, plus cache-aware single-page reads) go through here. The persistence
layer owns the SQL; this module shapes the response.
"""

from __future__ import annotations

from typing import Any

from mbforge.service.ports import get_repositories


def _row_to_result(row: dict[str, Any]) -> dict[str, Any]:
    """Map molecule_detections row → ExtractionResult-shaped dict."""
    moldet_conf = row["conf_moldet"] or 0.0
    return {
        "esmiles": row["vlm_verified_esmiles"] or "",
        "name": row["mol_id"] or "",
        "source": "image",
        "moldet_conf": moldet_conf,
        "bbox_pdf": [
            row["bbox_x0"] or 0.0,
            row["bbox_y0"] or 0.0,
            row["bbox_x1"] or 0.0,
            row["bbox_y1"] or 0.0,
        ],
        "page_idx": row["page"],
        "context_text": "",
        "mol_img_path": row["crop_relpath"],
        "status": "pending",
        "properties": {},
        # keep raw fields for callers that still expect SQL shape
        "mol_id": row["mol_id"],
        "doc_id": row["doc_id"],
        "page": row["page"],
        "bbox_x0": row["bbox_x0"],
        "bbox_y0": row["bbox_y0"],
        "bbox_x1": row["bbox_x1"],
        "bbox_y1": row["bbox_y1"],
        "crop_relpath": row["crop_relpath"],
        "conf_moldet": row["conf_moldet"],
    }


def load_cached_detections(library_root: str, doc_id: str, page: int) -> dict[str, Any]:
    rows = get_repositories(library_root).molecules.load_detections(doc_id, page)
    results = [_row_to_result(r) for r in rows]
    return {
        "success": True,
        "results": results,
        "detections": results,  # back-compat alias
        "count": len(results),
        "source": "cache" if results else "cache_miss",
    }


def load_all_cached_detections(library_root: str, doc_id: str) -> list[dict[str, Any]]:
    """Return every interactive ``molecule_detections`` row for *doc_id*.

    Document-level counterpart of :func:`load_cached_detections` — one query
    for all pages so the PDF viewer can prime its whole overlay in a single
    request instead of one query per page turn.
    """
    rows = get_repositories(library_root).molecules.load_detections(doc_id)
    return [_row_to_result(r) for r in rows]


def save_detections(library_root: str, detections: list[dict]) -> None:
    get_repositories(library_root).molecules.save_detections(detections)


def read_stats(library_root: str) -> dict[str, Any]:
    page_count, doc_count = get_repositories(library_root).molecules.detection_counts()
    return {
        "disk_usage_bytes": 0,
        "cached_page_count": page_count,
        "cached_doc_count": doc_count,
        "schema_version": 1,
    }


def clear_all(library_root: str) -> int:
    return get_repositories(library_root).molecules.clear_detections()


def clear_doc(library_root: str, doc_id: str) -> int:
    return get_repositories(library_root).molecules.clear_detections(doc_id)

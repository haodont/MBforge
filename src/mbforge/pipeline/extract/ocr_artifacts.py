"""Helpers for loading OCR artifacts from disk.

These functions let downstream stages read per-page OCR results without
holding the full response in memory during extraction.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.utils.files import load_json


def load_page_json(doc_id: str, library_root: str, page_num: int) -> dict | None:
    """Load a single page's OCR result from storage.

    Args:
        doc_id: Document identifier (e.g. ``72e86100-32c9-4cc7-acda-d29faeccf65f``).
        library_root: Root of the MBForge library (where ``storage/`` lives).
        page_num: 1-based page number.

    Returns:
        Parsed JSON dict with keys like ``text``, ``figure_bboxes``,
        ``ocr_backend``, etc. Returns ``None`` if the file does not exist or
        cannot be parsed.
    """
    pages_dir = Path(library_root) / "storage" / doc_id / "pages"
    json_path = pages_dir / f"page_{page_num:04d}.json"
    return load_json(json_path)

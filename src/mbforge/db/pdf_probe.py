"""PDF page-count probe for an imported document.

Only the page count is read here. Opening a PDF for ``page_count`` touches the
xref table and not the page contents, so the import path can afford it; text,
spans and layout belong to the Extract stage.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.domain.document import Document
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.db.pdf_probe")


def read_pdf_page_count(doc: Document) -> int:
    """Populate and return the document's page count from its PDF source.

    Returns the existing count for non-PDF files or when the source cannot be
    read — a bad PDF must not fail the import.
    """
    if Path(doc.file_name).suffix.lower() != ".pdf":
        return doc.page_count
    source = LibraryLayout(doc.library_root).storage_dir(doc.doc_id) / doc.file_name
    if not source.is_file():
        return doc.page_count
    try:
        import pymupdf

        with pymupdf.open(str(source)) as pdf:
            doc._page_count = pdf.page_count
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("Failed to read page count for %s: %s", doc.doc_id, exc)
        return doc.page_count
    return doc._page_count


__all__ = ["read_pdf_page_count"]

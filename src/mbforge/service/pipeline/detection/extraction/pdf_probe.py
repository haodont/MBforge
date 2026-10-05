"""PDF-level probes the molecule pass needs before it renders anything."""

from __future__ import annotations

from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.service.pipeline.detection.extraction.pdf_probe")


def open_pdf_errors() -> tuple[type[Exception], ...]:
    """Exceptions PyMuPDF raises for an unreadable or corrupt PDF."""
    import pymupdf

    errors: tuple[type[Exception], ...] = (RuntimeError,)
    if hasattr(pymupdf, "FileDataError"):
        errors += (pymupdf.FileDataError,)
    return errors


def read_page_count(
    pdf_path: str, open_errors: tuple[type[Exception], ...]
) -> int | None:
    """Page count of *pdf_path*, or None when the PDF cannot be opened.

    An unreadable PDF reports None rather than raising: the molecule pass is an
    enrichment over a document the layout producer already owns, so it degrades
    to "no molecules" instead of failing the run.
    """
    import pymupdf

    try:
        probe = pymupdf.open(pdf_path)
        try:
            return len(probe)
        finally:
            probe.close()
    except open_errors as exc:
        logger.error("Failed to open PDF %s: %s", pdf_path, exc)
        return None

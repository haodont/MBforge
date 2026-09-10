"""Pydantic models for the PDF router.

Schemas for the document overlay endpoint (``POST /api/v1/pdf/document-overlay``),
which feeds the PDF viewer's OCR panel and molecule overlay from one request.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field

from .detection_cache import DetectionResult


class _LibraryRootMixin(BaseModel):
    """Shared ``library_root`` field for PDF overlay requests."""

    library_root: str | None = Field(
        None,
        validation_alias=AliasChoices("library_root", "libraryRoot"),
        description="Library data directory; defaults to the configured root",
    )


class PdfDocumentOverlayRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/pdf/document-overlay``.

    ``doc_id`` is required: both payloads are read from SQL by document.
    """

    path: str = Field(..., description="PDF path (echoed back in the response)")
    doc_id: str = Field(
        ...,
        validation_alias=AliasChoices("doc_id", "docId"),
        description="Document identifier",
    )


class OcrBlock(BaseModel):
    """Single OCR layout block."""

    evidence_id: str
    page: int = 0
    block_type: str = ""
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    content: str | None = None
    index: int = 0
    angle: float = 0.0


class DocumentOverlayResponse(BaseModel):
    """Both page overlays of one document.

    ``blocks`` are the OCR layout blocks; ``pages`` are the molecule bboxes
    keyed by 1-based page (as JSON strings). ``source`` reports the molecule
    side: ``source_evidence`` when it contributed rows, else ``empty``.
    """

    success: bool = True
    path: str = ""
    from_cache: bool = False
    blocks: list[OcrBlock] = Field(default_factory=list)
    pages: dict[str, list[DetectionResult]] = Field(default_factory=dict)
    count: int = 0
    source: str = "empty"

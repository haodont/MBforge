"""PDF document-overlay endpoint.

Serves the PDF viewer's document overlay (``usePdfOverlay.ts`` →
``getDocumentOverlay``): OCR layout blocks for the text/figure panel plus
molecule bboxes for the molecule overlay, assembled from SQL by
:mod:`mbforge.application.use_cases.documents.pdf_layout`. The pipeline owns PDF
processing; this endpoint never reloads a run artifact.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from mbforge.application.dto.pdf import (
    DocumentOverlayResponse,
    PdfDocumentOverlayRequest,
)
from mbforge.application.use_cases.documents import pdf_layout
from mbforge.foundation.config import load_global_config
from mbforge.interfaces.http._path_utils import validate_doc_id

router = APIRouter()


@router.post("/document-overlay", response_model=DocumentOverlayResponse)
async def document_overlay(
    body: PdfDocumentOverlayRequest,
) -> DocumentOverlayResponse:
    """Layout blocks and molecule bboxes for one document, in one request."""
    validate_doc_id(body.doc_id)
    root = body.library_root or load_global_config().library_root or ""
    result = await asyncio.to_thread(
        pdf_layout.build_document_overlay, str(root), body.doc_id, body.path
    )
    return DocumentOverlayResponse(**result)

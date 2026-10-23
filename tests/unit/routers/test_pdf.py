from __future__ import annotations

import asyncio

import pytest

from mbforge.api.http.documents.pdf import document_overlay
from mbforge.foundation.layout import InvalidPathError
from mbforge.service.dto.pdf import PdfDocumentOverlayRequest


def test_document_overlay_returns_empty_payload_and_rejects_blank_doc_id(
    tmp_path,
) -> None:
    """An unreadable page yields an empty overlay; a blank doc_id never reaches
    the reader (it used to raise a raw layout error)."""
    result = asyncio.run(
        document_overlay(
            PdfDocumentOverlayRequest(
                path="/tmp/test.pdf", doc_id="doc-1", library_root=str(tmp_path)
            )
        )
    )
    assert result.path == "/tmp/test.pdf"
    assert result.blocks == []
    assert result.pages == {}
    assert result.source == "empty"

    with pytest.raises(InvalidPathError):
        asyncio.run(
            document_overlay(
                PdfDocumentOverlayRequest(
                    path="/tmp/test.pdf", doc_id="", library_root=str(tmp_path)
                )
            )
        )

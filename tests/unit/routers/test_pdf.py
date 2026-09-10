from __future__ import annotations

import asyncio

import pytest

from mbforge.models.pdf import PdfDocumentOverlayRequest
from mbforge.routers.documents.pdf import document_overlay
from mbforge.storage.layout import InvalidPathError


def test_document_overlay_returns_empty_payload(tmp_path) -> None:
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


def test_document_overlay_rejects_blank_doc_id(tmp_path) -> None:
    # A blank doc_id used to reach the reader and raise a raw layout error.
    with pytest.raises(InvalidPathError):
        asyncio.run(
            document_overlay(
                PdfDocumentOverlayRequest(
                    path="/tmp/test.pdf", doc_id="", library_root=str(tmp_path)
                )
            )
        )

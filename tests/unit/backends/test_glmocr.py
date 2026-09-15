"""Unit tests for the GLM-OCR cloud backend (layout_parsing v4).

Covers the two externally-visible contracts of ``GLMOCRBackend``:

1. Config opt-in: not configured without an API key, so default (cloud-only)
   settings never pull it into the chain.
2. ``extract_text`` decoding of a layout_parsing response into an ``OCRResult``
   carrying Markdown text plus layout spans, with the normalized ``bbox_2d``
   converted into PDF-point (bottom-left, 2 px/pt) space so MoleCode crop
   anchoring stays consistent with the PaddleOCR backends.
"""

from __future__ import annotations

import httpx
import pytest

from mbforge.backends.ocr.glmocr import (
    GLMOCRBackend,
    _bbox_to_pt,
    _spans_from_glm_result,
)


class _FakeClient:
    """Minimal ``httpx.Client`` stand-in with a context-manager interface."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.post_calls: list[dict] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def post(self, *args, **kwargs) -> httpx.Response:
        self.post_calls.append({"args": args, "kwargs": kwargs})
        return self._response


def _layout_payload() -> dict:
    """A minimal realistic layout_parsing payload for one page."""
    return {
        "id": "task_x",
        "created": 1,
        "model": "GLM-OCR",
        "md_results": "# Title\npage prose",
        "layout_details": [
            [
                {
                    "index": 1,
                    "label": "text",
                    "content": "page prose",
                    "bbox_2d": [0.1, 0.2, 0.9, 0.8],
                    "width": 1190,
                    "height": 1684,
                },
                {
                    "index": 2,
                    "label": "image",
                    "content": "http://img",
                    "bbox_2d": [0.3, 0.3, 0.4, 0.4],
                    "width": 1190,
                    "height": 1684,
                },
                {
                    "index": 3,
                    "label": "table",
                    "content": "<table>..</table>",
                    "bbox_2d": [0.0, 0.0, 0.5, 0.1],
                    "width": 1190,
                    "height": 1684,
                },
            ]
        ],
        "data_info": {"num_pages": 1, "pages": [{"width": 1190, "height": 1684}]},
    }


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "http://t"))


def test_glmocr_not_configured_without_api_key() -> None:
    assert GLMOCRBackend({}).is_configured() is False


def test_glmocr_configured_when_api_key_set() -> None:
    backend = GLMOCRBackend(
        {"api_key": "key", "host": "http://t/layout", "model": "glm-ocr"}
    )
    assert backend.is_configured() is True
    assert backend._cloud.base_url == "http://t/layout"


def test_glmocr_extract_text_decodes_text_and_spans(monkeypatch) -> None:
    client = _FakeClient(_response(_layout_payload()))
    monkeypatch.setattr(
        "mbforge.backends.ocr.glmocr.httpx.Client", lambda *a, **k: client
    )
    backend = GLMOCRBackend({"api_key": "key"})

    result = backend.extract_text(b"png bytes")

    assert result.text == "# Title\npage prose"
    assert result.error is None
    text_spans = [s for s in result.spans if s.block_type == 0]
    figures = [s for s in result.spans if s.block_type == 1]
    tables = [s for s in result.spans if s.block_type == 2]
    assert [s.text for s in text_spans] == ["page prose"]
    assert len(figures) == 1 and figures[0].text == ""
    assert len(tables) == 1

    # Request posts a JSON body with the base64 page image and the model.
    sent = client.post_calls[0]["kwargs"]
    assert sent["headers"]["Authorization"] == "Bearer key"
    assert sent["json"]["model"] == "glm-ocr"
    assert len(sent["json"]["file"]) > 0


def test_glmocr_returns_error_result_on_http_failure(monkeypatch) -> None:
    client = _FakeClient(
        httpx.Response(
            401,
            json={"error": {"code": "x", "message": "no"}},
            request=httpx.Request("POST", "http://t"),
        )
    )
    monkeypatch.setattr(
        "mbforge.backends.ocr.glmocr.httpx.Client", lambda *a, **k: client
    )
    result = GLMOCRBackend({"api_key": "key"}).extract_text(b"png")
    assert result.text == ""
    assert result.error is not None


def test_spans_from_glm_result_converts_normalized_bbox_to_pdf_points() -> None:
    """Normalized (top-left) bbox -> PDF-point (bottom-left) at 2 px/pt."""
    spans = _spans_from_glm_result(_layout_payload())
    text = [s for s in spans if s.block_type == 0][0]
    # page h = 1684px -> 842pt; y is flipped to bottom-left origin.
    assert text.bbox == pytest.approx((59.5, 168.4, 535.5, 673.6))
    assert text.text == "page prose"
    fig = [s for s in spans if s.block_type == 1][0]
    assert fig.bbox == pytest.approx((178.5, 505.2, 238.0, 589.4))


def test_bbox_to_pt_flips_y_to_bottom_left() -> None:
    # full-height normalized box covers the whole page in PDF points.
    assert _bbox_to_pt([0, 0, 1, 1], 1190, 1684) == (0.0, 0.0, 595.0, 842.0)


def test_spans_from_glm_result_returns_empty_for_bad_input() -> None:
    assert _spans_from_glm_result(None) == []
    assert _spans_from_glm_result({}) == []
    assert _spans_from_glm_result("garbage") == []

"""Unit tests for the PaddleOCR *local* GenAI backend.

Covers the two externally-visible contracts of ``LocalPaddleOCRBackend``:

1. Config opt-in: it is *not* configured unless a local ``host`` is set, so
   default (cloud-only) settings never pull the local backend into the chain.
2. ``extract_text`` decoding of a ``/layout-parsing`` response into an
   ``OCRResult`` carrying both Markdown text and layout spans (reusing the
   cloud backend's span decoding so MoleCode crop mapping stays consistent).
"""

from __future__ import annotations

import json as _json

import httpx

from mbforge.backends.ocr.ocr_local import (
    LocalPaddleOCRBackend,
    _spans_from_local_result,
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
    """A minimal realistic ``result`` for one page (image, text, table)."""
    return {
        "layoutParsingResults": [
            {
                "prunedResult": {
                    "width": 1191,
                    "height": 1684,
                    "parsing_res_list": [
                        {
                            "block_label": "text",
                            "block_bbox": [66, 1223, 1101, 1486],
                            "block_content": "page prose",
                        },
                        {
                            "block_label": "image",
                            "block_bbox": [214, 1056, 468, 1187],
                            "block_content": "",
                        },
                    ],
                },
                "markdown": {"text": "# Title\npage prose", "images": {}},
            }
        ]
    }


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "http://t"))


def test_local_backend_is_not_configured_without_host() -> None:
    assert LocalPaddleOCRBackend({}).is_configured() is False


def test_local_backend_is_configured_when_host_set() -> None:
    backend = LocalPaddleOCRBackend({"host": "http://127.0.0.1:8118"})
    assert backend.is_configured() is True


def test_local_backend_extract_text_decodes_layout_parsing(monkeypatch) -> None:
    payload = {
        "logId": "abc",
        "errorCode": 0,
        "errorMsg": "Success",
        "result": _layout_payload(),
    }
    client = _FakeClient(_response(payload))
    monkeypatch.setattr(
        "mbforge.backends.ocr.ocr_local.httpx.Client", lambda *a, **k: client
    )
    backend = LocalPaddleOCRBackend({"host": "http://127.0.0.1:8118"})

    result = backend.extract_text(b"png bytes")

    assert result.text == "# Title\npage prose"
    assert result.error is None
    # Reuses cloud span decoding: text span + one image figure.
    spans = result.spans
    text_spans = [s for s in spans if s.block_type == 0]
    figures = [s for s in spans if s.block_type == 1]
    assert [s.text for s in text_spans] == ["page prose"]
    assert len(figures) == 1
    # Request body is base64 image + disabled doc pre-processing.
    body = client.post_calls[0]["kwargs"]["content"]
    decoded = _json.loads(body)
    assert decoded.get("fileType") == 1
    assert decoded["file"].startswith("data:image/png;base64,")
    assert decoded["useDocOrientationClassify"] is False


def test_local_backend_returns_error_result_on_http_failure(monkeypatch) -> None:
    client = _FakeClient(_response({"errorCode": 1, "errorMsg": "boom"}))
    monkeypatch.setattr(
        "mbforge.backends.ocr.ocr_local.httpx.Client", lambda *a, **k: client
    )

    result = LocalPaddleOCRBackend({"host": "http://127.0.0.1:8118"}).extract_text(
        b"png bytes"
    )

    assert result.text == ""
    assert result.error is not None


def test_spans_from_local_result_returns_empty_for_bad_input() -> None:
    assert _spans_from_local_result(None) == []
    assert _spans_from_local_result({}) == []
    assert _spans_from_local_result("garbage") == []

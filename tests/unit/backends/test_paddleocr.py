"""Unit tests for the PaddleOCR cloud backend layout spans.

Covers the conversion of uploaded-image pixel bboxes (top-left origin,
144 DPI render) into bottom-left PDF-point spans, including figure
regions from parsing_res_list blocks and from markdown crop filenames.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from mbforge.backends.ocr.base import OCRCancelledError
from mbforge.backends.ocr.paddleocr import (
    PaddleOCRBackend,
    _px_bbox_to_pt,
    _spans_from_result,
)


def _page_payload(blocks: list[dict], image_names: list[str]) -> dict:
    return {
        "result": {
            "layoutParsingResults": [
                {
                    "prunedResult": {
                        "width": 1191,
                        "height": 1684,
                        "parsing_res_list": blocks,
                    },
                    "markdown": {"text": "", "images": dict.fromkeys(image_names, "")},
                }
            ]
        }
    }


def test_submit_keeps_bboxes_in_uploaded_image_coordinates() -> None:
    client = Mock()
    client.post.return_value = httpx.Response(
        200,
        json={"code": 0, "data": {"jobId": "job-1"}},
        request=httpx.Request("POST", "https://example.test"),
    )
    backend = PaddleOCRBackend({"api_key": "test-key"})

    assert backend._submit(client, "https://example.test/jobs", b"page") == "job-1"

    data = client.post.call_args.kwargs["data"]
    # Official PaddleOCR v2 example payload: three toggles, all defaulting False.
    assert json.loads(data["optionalPayload"]) == {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }


def test_submit_forwards_enabled_post_processing_toggles() -> None:
    """Enabled cloud post-processing toggles are passed verbatim to the submit."""
    client = Mock()
    client.post.return_value = httpx.Response(
        200,
        json={"code": 0, "data": {"jobId": "job-1"}},
        request=httpx.Request("POST", "https://example.test"),
    )
    backend = PaddleOCRBackend(
        {
            "api_key": "test-key",
            "doc_orientation_classify": True,
            "doc_unwarping": True,
            "chart_recognition": True,
        }
    )

    backend._submit(client, "https://example.test/jobs", b"page")

    data = client.post.call_args.kwargs["data"]
    assert json.loads(data["optionalPayload"]) == {
        "useDocOrientationClassify": True,
        "useDocUnwarping": True,
        "useChartRecognition": True,
    }


def test_extract_text_does_not_retry_client_http_errors(
    monkeypatch,
) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.post.return_value = httpx.Response(
        400,
        text="bad request",
        request=httpx.Request("POST", "https://example.test/jobs"),
    )
    monkeypatch.setattr(
        "mbforge.backends.ocr.paddleocr.httpx.Client",
        Mock(return_value=client),
    )

    result = PaddleOCRBackend({"api_key": "test-key"}).extract_text(b"page")

    assert result.text == ""
    assert client.post.call_count == 1


def test_extract_text_aborts_polling_when_cancelled(monkeypatch) -> None:
    """A cancel during polling stops the backend instead of waiting POLL_TIMEOUT.

    The v2 job API polls for minutes; without a checkpoint inside the loop the
    pipeline thread stays parked here after the user cancels.
    """
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.post.return_value = httpx.Response(
        200,
        json={"code": 0, "data": {"jobId": "job-1"}},
        request=httpx.Request("POST", "https://example.test/jobs"),
    )
    client.get.return_value = httpx.Response(
        200,
        json={"data": {"state": "running"}},
        request=httpx.Request("GET", "https://example.test/jobs/job-1"),
    )
    monkeypatch.setattr(
        "mbforge.backends.ocr.paddleocr.httpx.Client",
        Mock(return_value=client),
    )

    polls = {"n": 0}

    def cancel_check() -> None:
        polls["n"] += 1
        if polls["n"] >= 2:  # first poll iteration passes, second is cancelled
            raise RuntimeError("Pipeline cancelled by user")

    with pytest.raises(OCRCancelledError):
        PaddleOCRBackend({"api_key": "test-key"}).extract_text(
            b"page", cancel_check=cancel_check
        )

    assert polls["n"] == 2


def test_px_bbox_to_pt_flips_y_to_bottom_left() -> None:
    """1191x1684 px at 2 px/pt -> 595.5x842 pt; y flipped."""
    # block_bbox [64, 1196, 495, 1228] px top-left
    bbox = _px_bbox_to_pt([64, 1196, 495, 1228], 842.0, 0.5)
    assert bbox == (32.0, 228.0, 247.5, 244.0)


def test_spans_from_result_builds_text_and_image_spans() -> None:
    result_data = {
        "raw_results": [
            _page_payload(
                [
                    {
                        "block_label": "header",
                        "block_bbox": [497, 0, 669, 15],
                        "block_content": "476/546",
                    },
                    {
                        "block_label": "text",
                        "block_bbox": [66, 1223, 1101, 1486],
                        "block_content": "[0852] prose",
                    },
                    {
                        "block_label": "table",
                        "block_bbox": [80, 900, 500, 1100],
                        "block_content": "A | B",
                    },
                    {
                        "block_label": "image",
                        "block_bbox": [214, 1056, 468, 1187],
                        "block_content": "",
                    },
                ],
                [],
            )
        ]
    }
    spans = _spans_from_result(result_data)
    text_spans = [s for s in spans if s.block_type == 0]
    table_spans = [s for s in spans if s.block_type == 2]
    figures = [s for s in spans if s.block_type == 1]
    # header is page furniture and must be skipped.
    assert len(text_spans) == 1
    assert text_spans[0].text == "[0852] prose"
    assert len(table_spans) == 1
    assert table_spans[0].text == "A | B"
    assert len(figures) == 1
    assert figures[0].bbox == (107.0, 248.5, 234.0, 314.0)


def test_spans_from_result_reads_crop_filenames_and_dedupes() -> None:
    result_data = {
        "raw_results": [
            _page_payload(
                [
                    {
                        "block_label": "image",
                        "block_bbox": [214, 1056, 468, 1187],
                        "block_content": "",
                    }
                ],
                [
                    "imgs/img_in_image_box_214_1056_468_1187.jpg",
                    "imgs/img_in_image_box_214_1056_468_1187_2.jpg",
                    "imgs/img_in_image_box_97_200_230_320.jpg",
                ],
            )
        ]
    }
    spans = _spans_from_result(result_data)
    figures = [s for s in spans if s.block_type == 1]
    # parsing image block + first crop share a bbox; _2 suffix is a
    # duplicate crop of the same region -> 2 unique figures.
    assert len(figures) == 2
    assert figures[0].bbox == (107.0, 248.5, 234.0, 314.0)
    assert figures[1].bbox == (48.5, 682.0, 115.0, 742.0)


def test_spans_from_result_keeps_same_bbox_across_pages() -> None:
    result_data = {
        "raw_results": [
            _page_payload([], ["imgs/img_in_image_box_214_1056_468_1187.jpg"]),
            _page_payload([], ["imgs/img_in_image_box_214_1056_468_1187.jpg"]),
        ]
    }
    spans = _spans_from_result(result_data)
    assert len([s for s in spans if s.block_type == 1]) == 2


def test_spans_from_result_ignores_missing_or_bad_layout() -> None:
    assert _spans_from_result({"raw_results": [{"result": {}}]}) == []
    assert _spans_from_result({}) == []
    payload = _page_payload(
        [{"block_label": "text", "block_bbox": [0, 0], "block_content": "x"}], []
    )
    assert _spans_from_result({"raw_results": [payload]}) == []

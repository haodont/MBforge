"""PaddleOCR *local* backend — direct POST to the local GenAI ``/layout-parsing``.

MBForge's cloud PaddleOCR backend posts to aistudio-app.com's v2 async job
API, which is useless when no cloud API key is configured. This module adds a
**local entry point**: a PaddleOCR GenAI server deployed on-site (locally
served with a vLLM recognition backend, e.g. on ``127.0.0.1:8118``) exposes
the official sync layout-parsing endpoint::

    POST {host}/layout-parsing
    Content-Type: application/json
    {
      "file": "<Base64 PNG/JPEG, or an image/PDF URL>",
      "fileType": 1,
      "useDocOrientationClassify": false,
      "useDocUnwarping": false,
      ...
    }

    -> {
         "logId": "<uuid>",
         "errorCode": 0, "errorMsg": "Success",
         "result": {
           "layoutParsingResults": [{
             "prunedResult": {...},
             "markdown": {"text": "<markdown>", "images": {...} | null}
           }]
         }
       }

Reference: PaddleOCR servicing ("本地部署 / layout-parsing"), field semantics
map onto the PaddleOCR-VL ``predict``/``restructure_pages`` parameters.

The backend is **opt-in**: ``is_configured()`` is True only when a local
``host`` is set in the OCR config. When left empty the backend is dropped from
the chain and the cloud ``paddleocr`` path is unaffected. On any transport or
parse failure the backend returns ``OCRResult(error=...)`` so the fallback
chain moves on; local OCR failure must never fail extraction.
"""

from __future__ import annotations

import base64
import json

import httpx

from mbforge.utils.logger import get_logger

from .base import CancelCheck, OCRBackend, OCRResult, check_cancelled

logger = get_logger(__name__)

DEFAULT_LOCAL_HOST = ""
DEFAULT_LOCAL_MODEL = "PaddleOCR-VL-1.6"
REQUEST_TIMEOUT = 300.0  # local VLM inference on a full page can be slow
MAX_RESPONSE_TEXT = 200  # chars of response body to log for debugging

# Disabled pre-processing keeps PaddleOCR bboxes in the uploaded-image
# coordinate space, matching the cloud backend's render convention so molecode
# crop mapping stays correct (see paddOCR backend and LayoutSpan bbox scale).
_LAYOUT_BODY_BASE = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
}


class LocalPaddleOCRBackend(OCRBackend):
    """Direct client for a local PaddleOCR GenAI ``/layout-parsing`` endpoint."""

    name = "paddleocr_local"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        cfg = config or {}
        self._host = (cfg.get("host") or DEFAULT_LOCAL_HOST).strip().rstrip("/")
        self._model = (
            cfg.get("model") or DEFAULT_LOCAL_MODEL
        ).strip() or DEFAULT_LOCAL_MODEL
        self._timeout = float(cfg.get("timeout") or REQUEST_TIMEOUT)

    def is_configured(self) -> bool:
        # Opt-in: only participates in the chain when a local host is set.
        return bool(self._host)

    def extract_text(
        self, image: bytes, *, cancel_check: CancelCheck | None = None
    ) -> OCRResult:
        if not self._host:
            return OCRResult(text="", error="PaddleOCR local host not configured")

        # A single blocking POST with no poll loop: the only meaningful
        # checkpoint is before spending a REQUEST_TIMEOUT on a cancelled task.
        check_cancelled(cancel_check)

        body = dict(_LAYOUT_BODY_BASE)
        body["file"] = "data:image/png;base64," + base64.b64encode(image).decode(
            "ascii"
        )
        body["fileType"] = 1  # image
        body["useLayoutDetection"] = True

        try:
            with httpx.Client(timeout=self._timeout) as client:
                r = client.post(
                    self._layout_url(),
                    content=json.dumps(body),
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code != 200:
                    logger.warning(
                        "PaddleOCR local %s: %s",
                        r.status_code,
                        r.text[:MAX_RESPONSE_TEXT],
                    )
                r.raise_for_status()
                payload = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("PaddleOCR local request failed: %s", exc)
            return OCRResult(text="", error=str(exc))

        # errorCode is fixed to 0 on success (HTTP 200); a non-zero code
        # alongside 200 is malformed — treat it as a logical failure.
        if payload.get("errorCode") not in (None, 0):
            return OCRResult(
                text="", error=f"PaddleOCR local error {payload.get('errorCode')}"
            )

        result = payload.get("result") or {}
        text = self._extract_text(result)
        if not text.strip():
            logger.warning(
                "PaddleOCR local returned empty content: %s",
                str(payload)[:MAX_RESPONSE_TEXT],
            )
            return OCRResult(text="", error="PaddleOCR local returned empty content")

        spans = _spans_from_local_result(result)
        return OCRResult(text=text, spans=spans, raw_output=payload)

    # ------------------------------------------------------------------
    # Protocol helpers (separated so the exact request/response can be
    # calibrated against the real local server without touching the flow).
    # ------------------------------------------------------------------

    def _layout_url(self) -> str:
        # host may be the bare server root (…/8118) or include a prefix
        # (…/8118/v1); append the official relative endpoint verbatim.
        return f"{self._host}/layout-parsing"

    @staticmethod
    def _extract_text(result: dict) -> str:
        """Join every page's Markdown text from a layout-parsing result."""
        parts: list[str] = []
        for layout in result.get("layoutParsingResults") or []:
            if not isinstance(layout, dict):
                continue
            markdown = layout.get("markdown") or {}
            text = markdown.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        return "\n".join(parts)


# Deliberately not exposed as a public constructor: module-level helpers live
# here rather than on the class so the request/response decode stays easy to
# test at the lowest layer without bootstrapping an HTTP client.


def _spans_from_local_result(result: dict | None) -> list:
    """Decode layout spans from a local layout-parsing ``result``.

    Reuses the cloud backend's layout-scale convention (uploaded-image px at
    2 px/pt, bottom-left origin) so MoleCode crop mapping stays consistent.
    """
    from .paddleocr import _spans_from_result

    if not isinstance(result, dict):
        return []
    # The cloud decoder expects its own JSONL-shaped envelope: a list of
    # payloads, each carrying {"result": {"layoutParsingResults": [...]}}.
    envelopes = [
        {"result": {"layoutParsingResults": result.get("layoutParsingResults")}}
    ]
    return _spans_from_result({"raw_results": envelopes})

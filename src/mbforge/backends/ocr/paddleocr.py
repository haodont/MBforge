"""PaddleOCR cloud backend (v2 async API: submit → poll → result).

Posts a page image to the configured job endpoint, polls for completion,
and returns extracted text. The v2 API uses an async job pattern:
  POST {host}          (multipart file upload + model field) → {"data": {"jobId": "..."}}
  GET  {host}/{job_id} (poll until done)                     → {"data": {"state": "done", "resultUrl": {"jsonUrl": "..."}}}
  GET  {jsonUrl}       (download JSONL result)               → {"result": {"layoutParsingResults": [...]}}

Reference: PaddleOCR v2 API (official docs at https://ai.baidu.com/ai-doc/AISTUDIO/Mml7n69e7).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from mbforge.utils.files import safe_json_loads
from mbforge.utils.logger import get_logger

from .base import CloudOCRConfig, LayoutSpan, OCRBackend, OCRResult

logger = get_logger(__name__)

DEFAULT_HOST = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
POLL_INTERVAL = 5.0  # seconds between status checks
POLL_TIMEOUT = 300.0  # max seconds to wait for a job
REQUEST_TIMEOUT = 60.0  # per-request timeout
MAX_RESPONSE_TEXT = 200  # chars of response body to log for debugging

# The pipeline renders OCR page images at 144 DPI (zoom 2.0), i.e. 2 px
# per PDF point. Document unwarping/orientation preprocessing is disabled on
# submit so PaddleOCR bboxes stay in the uploaded-image coordinate space. We
# convert them into PDF-point space with a bottom-left origin so molecule
# detection can crop ROIs directly (see LayoutSpan).
_OCR_RENDER_PX_PER_PT = 2.0

_TEXT_LABELS = {"text", "paragraph_title", "formula"}
_TABLE_LABELS = {"table"}
_IMAGE_LABELS = {"image"}

# Markdown image keys embed the crop bbox in pixels:
# imgs/img_in_image_box_<x0>_<y0>_<x1>_<y1>[.jpg]
_CROP_BBOX_RE = re.compile(r"img_in_image_box_(\d+)_(\d+)_(\d+)_(\d+)")


class PaddleOCRBackend(OCRBackend):
    name = "paddleocr"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self._cloud = CloudOCRConfig.from_config(
            config,
            base_url_default=DEFAULT_HOST,
            model_default="PaddleOCR-VL-1.6",
            base_url_key="host",
        )
        # Post-processing toggles forwarded into the submit `optionalPayload`.
        # Defaults keep the uploaded-image geometry unchanged (the bbox→PDF-point
        # mapping depends on it); each may be enabled via OCRConfig.
        self._optional_payload = {
            "useDocOrientationClassify": bool(
                (config or {}).get("doc_orientation_classify", False)
            ),
            "useDocUnwarping": bool((config or {}).get("doc_unwarping", False)),
            "useChartRecognition": bool((config or {}).get("chart_recognition", False)),
        }

    def is_configured(self) -> bool:
        return self._cloud.is_configured()

    def extract_text(self, image: bytes) -> OCRResult:
        if not self.is_configured():
            return OCRResult(text="", error="PaddleOCR api_key not set")

        base = self._cloud.base_url

        # Retry transient provider failures; client errors are terminal.
        max_retries = 3
        retry_delay = 5.0  # seconds

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                    # 1) Submit — upload image with model field, get job_id
                    job_id = self._submit(client, base, image)
                    if not job_id:
                        if attempt < max_retries - 1:
                            logger.info(
                                "PaddleOCR submit failed, retrying in %.0fs (attempt %d/%d)",
                                retry_delay,
                                attempt + 1,
                                max_retries,
                            )
                            time.sleep(retry_delay)
                            continue
                        return OCRResult(text="", error="PaddleOCR: no job_id returned")

                    # 2) Poll — wait for completion, get result URL
                    result_data = self._poll(client, base, job_id)
                    if result_data is None:
                        return OCRResult(
                            text="",
                            error=f"PaddleOCR: job {job_id} did not complete within {POLL_TIMEOUT}s",
                        )

                    # 3) Parse result
                    text = self._extract_text(result_data)
                    images = result_data.pop("_downloaded_images", {})
                    spans = _spans_from_result(result_data)
                    return OCRResult(
                        text=text, images=images, spans=spans, raw_output=result_data
                    )

            except Exception as exc:  # noqa: BLE001
                status_code = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                if (
                    status_code is not None
                    and 400 <= status_code < 500
                    and status_code != 429
                ):
                    logger.warning(
                        "PaddleOCR request rejected with HTTP %d; not retrying",
                        status_code,
                    )
                    return OCRResult(text="", error=str(exc))
                if attempt < max_retries - 1:
                    logger.info(
                        "PaddleOCR attempt %d/%d failed: %s, retrying in %.0fs",
                        attempt + 1,
                        max_retries,
                        exc,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    continue
                logger.warning(
                    "PaddleOCR failed after %d attempts: %s", max_retries, exc
                )
                return OCRResult(text="", error=str(exc))

        return OCRResult(text="", error="PaddleOCR: max retries exceeded")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _submit(self, client: httpx.Client, base: str, image: bytes) -> str | None:
        """Upload image with model field and return job_id."""
        # Three post-processing toggles, matching the official PaddleOCR v2
        # example payload verbatim. Defaults are all False so bboxes stay in the
        # uploaded-image coordinate space; each is configurable via OCRConfig.
        optional_payload = dict(self._optional_payload)
        r = client.post(
            base,
            headers=self._cloud.auth_headers(),
            data={
                "model": self._cloud.model,
                "optionalPayload": json.dumps(optional_payload),
            },
            files={"file": ("page.png", image, "image/png")},
        )
        if r.status_code != 200:
            logger.warning(
                "PaddleOCR submit %s: %s",
                r.status_code,
                r.text[:MAX_RESPONSE_TEXT],
            )
        r.raise_for_status()
        payload = r.json()

        # Check API error code
        if payload.get("code") != 0:
            logger.warning(
                "PaddleOCR submit error: %s (code=%s)",
                payload.get("msg"),
                payload.get("code"),
            )
            return None

        # Extract jobId from data field
        data = payload.get("data") or {}
        job_id = data.get("jobId")
        if job_id:
            logger.debug("PaddleOCR job submitted: %s", job_id)
        else:
            logger.warning(
                "PaddleOCR submit response has no jobId: %s",
                json.dumps(payload)[:MAX_RESPONSE_TEXT],
            )
        return job_id

    def _poll(self, client: httpx.Client, base: str, job_id: str) -> dict | None:
        """Poll job status until done/failed or timeout.

        Returns the parsed result dict on success, None on timeout/failure.
        """
        status_url = f"{base}/{job_id}"
        deadline = time.monotonic() + POLL_TIMEOUT

        while time.monotonic() < deadline:
            r = client.get(
                status_url,
                headers=self._cloud.auth_headers(),
            )
            r.raise_for_status()
            payload = r.json()
            data = payload.get("data") or {}
            state = data.get("state")

            if state == "done":
                # Result is in resultUrl.jsonUrl (BOS URL serving JSONL)
                result_url = data.get("resultUrl") or {}
                json_url = result_url.get("jsonUrl")
                if json_url:
                    return self._fetch_result(client, json_url)
                logger.warning("PaddleOCR job %s done but no jsonUrl", job_id)
                return None

            if state == "failed":
                err = data.get("errorMsg") or "unknown"
                logger.warning("PaddleOCR job %s failed: %s", job_id, err)
                return None

            # Still pending or running
            time.sleep(POLL_INTERVAL)

        logger.warning("PaddleOCR job %s timed out after %.0fs", job_id, POLL_TIMEOUT)
        return None

    def _fetch_result(self, client: httpx.Client, json_url: str) -> dict | None:
        """Download and parse JSONL result from BOS URL."""
        r = client.get(json_url)  # BOS URL, no auth header needed
        r.raise_for_status()

        parts: list[str] = []
        raw_results: list[dict] = []
        downloaded_images: dict[str, bytes] = {}
        for line in r.text.splitlines():
            if not line.strip():
                continue
            payload = safe_json_loads(line, {})
            if not isinstance(payload, dict):
                continue
            raw_results.append(payload)
            result = payload.get("result") or {}
            if not isinstance(result, dict):
                continue

            # PaddleOCR-VL: layoutParsingResults with markdown text
            for res in result.get("layoutParsingResults", []):
                markdown = res.get("markdown") or {}
                text = markdown.get("text", "")
                if text:
                    parts.append(text)
                # Only download molecule images from markdown.images, skip outputImages (layout debug)
                self._download_images(
                    client,
                    markdown.get("images"),
                    downloaded_images,
                )

            # PP-OCRv5: ocrResults with rec_texts (fallback)
            for res in result.get("ocrResults", []):
                rec_texts = res.get("rec_texts") or []
                if rec_texts:
                    parts.append("\n".join(rec_texts))

        return {
            "text": "\n".join(parts),
            "raw_results": raw_results,
            "_downloaded_images": downloaded_images,
        }

    @staticmethod
    def _download_images(
        client: httpx.Client,
        image_urls: object,
        downloaded_images: dict[str, bytes],
    ) -> None:
        if not isinstance(image_urls, dict):
            return
        for name, url in image_urls.items():
            if not isinstance(name, str) or not isinstance(url, str):
                continue
            if not url.startswith(("http://", "https://")):
                continue
            filename = name
            if not Path(filename).suffix:
                filename += Path(urlparse(url).path).suffix or ".bin"
            try:
                response = client.get(url)
                response.raise_for_status()
                downloaded_images[filename] = response.content
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "PaddleOCR image download failed for %s: %s", filename, exc
                )

    @staticmethod
    def _extract_text(payload: dict) -> str:
        """Extract text from parsed result dict."""
        return payload.get("text", "")


def _px_bbox_to_pt(
    bbox: list | tuple, page_h_pt: float, scale: float
) -> tuple[float, float, float, float]:
    """Convert an uploaded-image pixel bbox (top-left origin) to PDF points."""
    x0, y0, x1, y1 = (float(v) for v in bbox)
    ax0, ax1 = sorted((x0 * scale, x1 * scale))
    y_top_pt, y_bot_pt = sorted((y0 * scale, y1 * scale))
    return (ax0, page_h_pt - y_bot_pt, ax1, page_h_pt - y_top_pt)


def _spans_from_result(result_data: dict) -> list[LayoutSpan]:
    """Convert PaddleOCR layout results into PDF-point layout spans.

    Figure regions come from two sources, deduplicated per page: image
    blocks in ``prunedResult.parsing_res_list`` and structure crops whose
    bbox is embedded in the markdown image filename (crops inside tables
    do not appear as standalone image blocks).
    """
    spans: list[LayoutSpan] = []
    scale = 1.0 / _OCR_RENDER_PX_PER_PT
    for payload in result_data.get("raw_results") or []:
        result = payload.get("result") or {}
        for layout in result.get("layoutParsingResults") or []:
            pruned = layout.get("prunedResult")
            if not isinstance(pruned, dict):
                continue
            page_w_px = float(pruned.get("width") or 0)
            page_h_px = float(pruned.get("height") or 0)
            if page_w_px <= 0 or page_h_px <= 0:
                continue
            page_h_pt = page_h_px * scale
            figures: set[tuple[float, float, float, float]] = set()

            def add_figure(
                figures: set[tuple[float, float, float, float]],
                bbox_pt: tuple[float, float, float, float],
            ) -> None:
                if bbox_pt not in figures:
                    figures.add(bbox_pt)
                    spans.append(LayoutSpan(text="", bbox=bbox_pt, block_type=1))

            for block in pruned.get("parsing_res_list") or []:
                if not isinstance(block, dict):
                    continue
                label = block.get("block_label") or ""
                bbox = block.get("block_bbox")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                bbox_pt = _px_bbox_to_pt(bbox, page_h_pt, scale)
                if label in _IMAGE_LABELS:
                    add_figure(figures, bbox_pt)
                elif label in _TEXT_LABELS | _TABLE_LABELS:
                    content = block.get("block_content") or ""
                    if content:
                        spans.append(
                            LayoutSpan(
                                text=content,
                                bbox=bbox_pt,
                                block_type=2 if label in _TABLE_LABELS else 0,
                            )
                        )

            markdown = layout.get("markdown") or {}
            for name in markdown.get("images") or {}:
                m = _CROP_BBOX_RE.search(str(name))
                if not m:
                    continue
                add_figure(
                    figures,
                    _px_bbox_to_pt([int(v) for v in m.groups()], page_h_pt, scale),
                )
    return spans

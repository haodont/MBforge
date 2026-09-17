"""GLM-OCR cloud backend (Zhipu BigModel ``layout_parsing`` v4 API).

Synchronous, Bearer-authenticated endpoint that parses one page image (or a
PDF) into Markdown text plus normalized layout details::

    POST /paas/v4/layout_parsing
    Authorization: Bearer {api_key}
    {
      "model": "glm-ocr",
      "file": "<base64 image, or a URL>"
    }

    -> {
         "id": "...", "created": ..., "model": "GLM-OCR",
         "md_results": "<markdown text>",
         "layout_details": [[LayoutDetail, ...]],
         "data_info": {"num_pages": 1, "pages": [{"width":..,"height":..}]},
         ...
       }

Each ``LayoutDetail`` carries a normalized ``bbox_2d`` in [0,1] (top-left
origin over the uploaded image) plus per-element ``height``/``width`` page
dimensions. MBForge renders one page per request (``extract_text`` receives a
single PNG), so ``layout_details`` always holds one page.

Reference: https://docs.bigmodel.cn / GLM-OCR `文档解析` (layout_parsing).

This backend is opt-in via ``glmocr_api_key``; unconfigured it is silently
dropped from the chain. On transport/parse failure it returns
``OCRResult(error=...)`` so the fallback chain moves on.
"""

from __future__ import annotations

import base64

import httpx

from mbforge.utils.logger import get_logger

from .base import (
    CancelCheck,
    CloudOCRConfig,
    LayoutSpan,
    OCRBackend,
    OCRResult,
    check_cancelled,
)

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
DEFAULT_MODEL = "glm-ocr"
REQUEST_TIMEOUT = 120.0  # cloud VLM inference on a full page can take tens of s
MAX_RESPONSE_TEXT = 200  # chars of response body to log on failure

#: px/pt of the 144-DPI page render (matches _OCR_RENDER_PX_PER_PT so spans stay
#: in the same PDF-point coordinate convention as the cloud PaddleOCR backend).
_PX_PER_PT = 2.0

# LayoutDetail.label -> LayoutSpan.block_type (0=text, 1=image, 2=table).
_LABEL_BLOCK_TYPE = {"image": 1, "table": 2}


class GLMOCRBackend(OCRBackend):
    """Direct client for the Zhipu GLM-OCR layout_parsing endpoint."""

    name = "glmocr"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self._cloud = CloudOCRConfig.from_config(
            config,
            base_url_default=DEFAULT_BASE_URL,
            model_default=DEFAULT_MODEL,
            base_url_key="host",
        )

    def is_configured(self) -> bool:
        return self._cloud.is_configured()

    def extract_text(
        self, image: bytes, *, cancel_check: CancelCheck | None = None
    ) -> OCRResult:
        if not self._cloud.is_configured():
            return OCRResult(text="", error="GLM-OCR api_key not set")

        # A single blocking POST with no poll loop: the only meaningful
        # checkpoint is before spending a REQUEST_TIMEOUT on a cancelled task.
        check_cancelled(cancel_check)

        body = {
            "model": self._cloud.model,
            "file": base64.b64encode(image).decode("ascii"),
        }
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                r = client.post(
                    self._cloud.base_url,
                    headers=self._cloud.auth_headers("application/json"),
                    json=body,
                )
                if r.status_code != 200:
                    logger.warning(
                        "GLM-OCR layout_parsing %s: %s",
                        r.status_code,
                        r.text[:MAX_RESPONSE_TEXT],
                    )
                r.raise_for_status()
                payload = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GLM-OCR request failed: %s", exc)
            return OCRResult(text="", error=str(exc))

        text = payload.get("md_results") or ""
        if not text.strip():
            logger.warning(
                "GLM-OCR returned empty md_results: %s",
                str(payload)[:MAX_RESPONSE_TEXT],
            )
            # A page with no parseable content is an empty OCRResult, not an
            # error: the chain's "first non-empty wins" semantics still apply.
            return OCRResult(text="", error="GLM-OCR returned empty md_results")

        spans = _spans_from_glm_result(payload)
        return OCRResult(text=text, spans=spans, raw_output=payload)


def _spans_from_glm_result(payload: dict | None) -> list[LayoutSpan]:
    """Decode normalized GLM layout details into PDF-point layout spans.

    ``bbox_2d`` is normalized [x1, y1, x2, y2] over the uploaded image with a
    top-left origin. Converted to PDF points with a bottom-left origin at the
    pipeline's 2 px/pt scale so MoleCode crop anchoring stays consistent.
    """
    if not isinstance(payload, dict):
        return []
    details = payload.get("layout_details")
    if not isinstance(details, list) or not details:
        return []
    # Single page input => the first (and only) inner list is that page.
    page_details = details[0] if isinstance(details[0], list) else details
    data_info = payload.get("data_info") or {}
    pages = data_info.get("pages") or []
    fallback_page = pages[0] if pages else {}

    spans: list[LayoutSpan] = []
    for d in page_details:
        if not isinstance(d, dict):
            continue
        label = d.get("label")
        if label not in ("image", "table", "text", "formula"):
            continue
        bbox = d.get("bbox_2d")
        if not _looks_like_bbox(bbox):
            continue
        w = _num(d.get("width")) or _num(fallback_page.get("width"))
        h = _num(d.get("height")) or _num(fallback_page.get("height"))
        if not w or not h:
            continue
        x0, y0, x1, y1 = _bbox_to_pt(bbox, w, h)
        block_type = _LABEL_BLOCK_TYPE.get(label, 0)
        spans.append(
            LayoutSpan(
                text=d.get("content") if block_type != 1 else "",
                bbox=(x0, y0, x1, y1),
                block_type=block_type,
            )
        )
    return spans


def _looks_like_bbox(bbox) -> bool:
    return (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(isinstance(v, (int, float)) for v in bbox)
    )


def _num(v):
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _bbox_to_pt(
    bbox, width_px: float, height_px: float, px_per_pt: float = _PX_PER_PT
) -> tuple[float, float, float, float]:
    """Normalized (top-left) bbox -> PDF-point (bottom-left) bbox."""
    scale = 1.0 / px_per_pt
    ax0 = bbox[0] * width_px * scale
    ax1 = bbox[2] * width_px * scale
    x0, x1 = sorted((ax0, ax1))
    y_top_pt = bbox[1] * height_px * scale
    y_bot_pt = bbox[3] * height_px * scale
    page_h_pt = height_px * scale
    return (x0, page_h_pt - y_bot_pt, x1, page_h_pt - y_top_pt)

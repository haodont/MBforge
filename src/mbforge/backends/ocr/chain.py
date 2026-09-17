"""OCR fallback chain.

Default priority for PDF text extraction:

    PaddleOCR

Each backend in turn is asked to OCR the page. The first one that returns
non-empty text wins. If every configured backend fails or returns empty, the
chain returns an ``OCRResult`` with an explicit error; if no backend is
configured at all, it raises ``OCRUnavailableError``.

`load_chain()` builds the chain from the live AppConfig.ocr dict so
changes to settings.json take effect on the next call.

Design note (2026-07 audit): the multi-backend fallback is an intentional
resilience feature, not a leftover compatibility branch. Scanned-page OCR is
the only path for image-only documents, so losing one provider (rate limit,
outage, key expiry) must degrade to the next configured provider instead of
failing the document. Do not remove a backend from ``DEFAULT_PRIORITY``
without a provider-reliability tradeoff recorded elsewhere.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from mbforge.utils.logger import get_logger

from .base import CancelCheck, OCRBackend, OCRCancelledError, OCRResult
from .glmocr import GLMOCRBackend
from .ocr_local import LocalPaddleOCRBackend
from .paddleocr import PaddleOCRBackend

logger = get_logger(__name__)

# Cloud first, optional local PaddleOCR fallback last. The local backend
# participates only when a ``paddleocr_local_host`` is configured (opt-in);
# GLM-OCR participates only when ``glmocr_api_key`` is set (opt-in).
DEFAULT_PRIORITY: tuple[str, ...] = ("paddleocr", "glmocr", "paddleocr_local")


class OCRUnavailableError(RuntimeError):
    """Raised when no configured OCR backend can process a scanned page."""


def _ocr_config_to_dict(ocr_config: dict | Any | None) -> dict[str, Any]:
    """Normalize ``OCRConfig`` model or plain dict into a dict."""
    if ocr_config is None:
        return {}
    if isinstance(ocr_config, dict):
        return ocr_config
    if hasattr(ocr_config, "model_dump"):
        return ocr_config.model_dump()
    return {}


def _priority_from_config(cfg: dict[str, Any]) -> list[str]:
    """Return a validated priority list with deterministic default completion."""
    configured = cfg.get("priority")
    if not isinstance(configured, list):
        configured = []
    selected: list[str] = []
    for name in configured:
        if name in DEFAULT_PRIORITY and name not in selected:
            selected.append(name)
    selected.extend(name for name in DEFAULT_PRIORITY if name not in selected)
    return selected


def build_backends(ocr_config: dict | Any | None) -> list[OCRBackend]:
    """Build backends in priority order from config.

    Backends that aren't configured (no api_key etc.) are silently
    dropped so the chain doesn't try them.
    """
    cfg = _ocr_config_to_dict(ocr_config)
    paddle_cfg = {
        "api_key": cfg.get("paddleocr_api_key", ""),
        "host": cfg.get("paddleocr_host", ""),
        "model": cfg.get("paddleocr_model", "PaddleOCR-VL-1.6"),
        "doc_orientation_classify": bool(
            cfg.get("paddleocr_doc_orientation_classify", False)
        ),
        "doc_unwarping": bool(cfg.get("paddleocr_doc_unwarping", False)),
        "chart_recognition": bool(cfg.get("paddleocr_chart_recognition", False)),
    }
    local_cfg = {
        "api_key": cfg.get("paddleocr_local_api_key", ""),
        "host": cfg.get("paddleocr_local_host", ""),
        "model": cfg.get("paddleocr_local_model", ""),
    }
    glm_cfg = {
        "api_key": cfg.get("glmocr_api_key", ""),
        "host": cfg.get("glmocr_base_url", ""),
        "model": cfg.get("glmocr_model", "glm-ocr"),
    }

    candidates = {
        "paddleocr": lambda: PaddleOCRBackend(paddle_cfg),
        "glmocr": lambda: GLMOCRBackend(glm_cfg),
        "paddleocr_local": lambda: LocalPaddleOCRBackend(local_cfg),
    }
    backends: list[OCRBackend] = []
    for name in _priority_from_config(cfg):
        backend = candidates[name]()
        if backend.is_configured():
            backends.append(backend)
    return backends


def extract_text_with_chain(
    image: bytes,
    ocr_config: dict | Any | None,
    *,
    backends: list[OCRBackend] | None = None,
    cancel_check: CancelCheck | None = None,
) -> OCRResult:
    """Run OCR through the fallback chain. Returns the first non-empty result.

    ``cancel_check`` is forwarded to each backend's poll loop. A backend that
    observes it raises ``OCRCancelledError``, which is re-raised here: a
    cancelled task must never be degraded into "this provider failed" and
    fall through to the next one.
    """
    chain = backends if backends is not None else build_backends(ocr_config)
    if not chain:
        raise OCRUnavailableError("no OCR backend configured")
    last_error: str | None = None
    last_result: OCRResult | None = None
    started = time.perf_counter()
    for attempt, backend in enumerate(chain, start=1):
        try:
            result = backend.extract_text(image, cancel_check=cancel_check)
        except OCRCancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            result = OCRResult(text="", error=str(exc))
        result.backend = backend.name
        result.chain_attempts = attempt
        result.elapsed_ms = round((time.perf_counter() - started) * 1000)
        last_result = result
        if result.text.strip():
            logger.info(
                "OCR chain succeeded with backend=%s after %d attempt(s)",
                backend.name,
                attempt,
            )
            return result
        last_error = result.error or f"{backend.name} returned empty"
    logger.warning("OCR chain exhausted without text: %s", last_error)
    if last_result is None:
        return OCRResult(text="", error=last_error or "all backends returned empty")
    last_result.error = last_error or "all backends returned empty"
    return last_result


def list_configured_backends(ocr_config: dict | Any | None) -> Iterable[str]:
    """Names of backends that would participate in the chain."""
    return [b.name for b in build_backends(ocr_config)]

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
from pathlib import Path
from typing import Any

from mbforge.utils.logger import get_logger

from .base import OCRBackend, OCRResult
from .ocr_local import LocalPaddleOCRBackend
from .paddleocr import PaddleOCRBackend

logger = get_logger(__name__)

# Cloud first, optional local PaddleOCR fallback second. The local backend
# participates only when a ``paddleocr_local_host`` is configured (opt-in).
DEFAULT_PRIORITY: tuple[str, ...] = ("paddleocr", "paddleocr_local")


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

    candidates = {
        "paddleocr": lambda: PaddleOCRBackend(paddle_cfg),
        "paddleocr_local": lambda: LocalPaddleOCRBackend(local_cfg),
    }
    backends: list[OCRBackend] = []
    for name in _priority_from_config(cfg):
        backend = candidates[name]()
        if backend.is_configured():
            backends.append(backend)
    return backends


def _save_images(result: OCRResult, save_images_dir: str | Path | None) -> None:
    """Persist molecule images from an OCRResult to disk.

    Only saves images from markdown.images (molecule crops), skipping
    layout debug images like layout_det_res*.jpg from outputImages.
    Long filenames are hashed to avoid Windows MAX_PATH limits.
    """
    if not save_images_dir or not result.images:
        return
    target_dir = Path(save_images_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, data in result.images.items():
        # Skip layout debug images (from PaddleOCR outputImages)
        if filename.startswith("layout_det_res"):
            continue

        # Backends emit relative names with subdirs (e.g. "imgs/abc.jpg"); the
        # layout contract stores images flat under images_dir and markdown
        # rewrites reference the basename, so keep only the basename.
        relative = Path(Path(filename).name)

        # Windows MAX_PATH limit (260 chars): hash long filenames to stay safe.
        # Even if the full path is under 260, a very long filename can cause
        # [Errno 22] Invalid argument on some Windows APIs.
        _max_filename_len = 120  # Conservative limit for filename alone
        if len(relative.name) > _max_filename_len:
            import hashlib

            stem = relative.stem[:40]  # Keep first 40 chars for readability
            suffix = relative.suffix
            hash_part = hashlib.md5(relative.name.encode()).hexdigest()[:8]
            safe_name = f"{stem}_{hash_part}{suffix}"
            relative = Path(safe_name)

        target = target_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        counter = 2
        while target.exists():
            target = target.with_name(f"{target.stem}_{counter}{target.suffix}")
            counter += 1
        target.write_bytes(data)


def _save_raw_output(result: OCRResult, save_images_dir: str | Path | None) -> None:
    """Save raw OCR backend response as JSON for debugging/analysis.

    The raw_output contains the full API response (e.g., PaddleOCR's
    layoutParsingResults with bounding boxes, confidence scores, etc.).
    Saved alongside images in the same directory as ocr_result.json.
    """
    if not save_images_dir or not result.raw_output:
        return
    target_dir = Path(save_images_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "ocr_result.json"
    try:
        import json

        json_path.write_text(
            json.dumps(result.raw_output, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save OCR raw output: %s", exc)


def extract_text_with_chain(
    image: bytes,
    ocr_config: dict | Any | None,
    save_images_dir: str | Path | None = None,
    *,
    backends: list[OCRBackend] | None = None,
) -> OCRResult:
    """Run OCR through the fallback chain. Returns the first non-empty result.

    If ``save_images_dir`` is provided and the winning backend returned images,
    they are written to that directory using the backend's filename keys.
    """
    chain = backends if backends is not None else build_backends(ocr_config)
    if not chain:
        raise OCRUnavailableError("no OCR backend configured")
    last_error: str | None = None
    last_result: OCRResult | None = None
    started = time.perf_counter()
    for attempt, backend in enumerate(chain, start=1):
        try:
            result = backend.extract_text(image)
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
            _save_images(result, save_images_dir)
            _save_raw_output(result, save_images_dir)
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

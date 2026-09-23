"""Crop-label OCR backend — MolDet-style process-wide lifecycle.

Mirrors the MolDet/MolParser backend shape: a process-wide lazy singleton
with ``get_label_reader()`` / ``unload()`` / ``health()``, engine selection
from ``moldet.ocr_engine`` (``onnx`` default, ``torch`` optional), and per
thread engine ownership (so the OCR pool may read concurrently). RapidOCR
weights are pulled by the package itself on first use (no ResourceManager
staging), matching the "package-internal autodownload" maintenance model.
"""

from __future__ import annotations

import threading

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

_reader_singleton = None
_reader_lock = threading.Lock()


def _engine_name_from_config() -> str:
    """Return the configured engine name (``onnx``/``torch``)."""
    from mbforge.adapters.inference.ocr.crop_labels import _engine_name

    return _engine_name()


def _ocr_mode_from_config() -> str:
    """Return the configured OCR deployment mode (``inprocess``/``daemon``)."""
    from mbforge.adapters.inference.ocr.crop_labels import _ocr_mode

    return _ocr_mode()


class LabelReader:
    """Read compound-identifier labels off molecule crop "others" offcuts."""

    def __init__(self) -> None:
        self._engine = _engine_name_from_config()
        self._mode = _ocr_mode_from_config()

    @property
    def engine_name(self) -> str:
        return self._engine

    @property
    def mode(self) -> str:
        return self._mode

    def is_available(self) -> bool:
        """Whether an engine can be created for the configured engine name."""
        if self._mode == "daemon":
            from mbforge.adapters.inference.ocr.daemon_client import get_daemon_client

            try:
                return get_daemon_client().is_available
            except Exception as exc:
                logger.warning("OCR daemon unavailable: %s", exc)
                return False
        from mbforge.adapters.inference.ocr.crop_labels import (
            _create_engine,
            _engine_name,
        )

        try:
            engine = _create_engine(_engine_name())
            if engine is not None:
                return True
            logger.warning("Crop-label OCR engine unavailable (no usable backend)")
            return False
        except Exception as exc:
            logger.warning("Crop-label OCR engine unavailable: %s", exc)
            return False

    def read(self, image):
        """OCR an offcut; return ``[(text, conf, bbox, isolated), ...]``.

        In-process mode delegates to ``crop_labels.extract_label_reads``, which
        owns filtering, per-thread engine reuse, and the GPU gate. Daemon mode
        forwards the image to the persistent background OCR process.
        """
        if self._mode == "daemon":
            from mbforge.adapters.inference.ocr.daemon_client import get_daemon_client

            return get_daemon_client().read(image)
        from mbforge.adapters.inference.ocr.crop_labels import extract_label_reads

        return extract_label_reads(image)

    def unload(self) -> None:
        """Release cached engines; the next call recreates them lazily."""
        if self._mode == "daemon":
            from mbforge.adapters.inference.ocr.daemon_client import unload_daemon

            unload_daemon()
            self._engine = _engine_name_from_config()
            return
        from mbforge.adapters.inference.ocr import crop_labels

        crop_labels._clear_engines()
        self._engine = _engine_name_from_config()


def get_label_reader() -> LabelReader:
    """Return the process-wide crop-label OCR singleton (thread-safe)."""
    global _reader_singleton
    if _reader_singleton is None:
        with _reader_lock:
            if _reader_singleton is None:
                _reader_singleton = LabelReader()
    return _reader_singleton


def unload() -> None:
    """Release the backend singleton and its cached engines."""
    global _reader_singleton
    with _reader_lock:
        if _reader_singleton is not None:
            _reader_singleton.unload()
            _reader_singleton = None


def health() -> dict[str, str]:
    """Backend health snapshot for readiness reports."""
    reader = get_label_reader()
    available = reader.is_available()
    return {
        "status": "ready" if available else "unavailable",
        "engine": reader.engine_name,
        "error": "" if available else "no usable OCR backend",
    }

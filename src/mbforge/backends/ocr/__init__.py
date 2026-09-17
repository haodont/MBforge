"""OCR backends — cloud-first chain.

Default priority for PDF text extraction is set in `chain.DEFAULT_PRIORITY`:

    PaddleOCR
"""

from .base import OCRBackend, OCRCancelledError, OCRResult
from .chain import (
    DEFAULT_PRIORITY,
    build_backends,
    extract_text_with_chain,
    list_configured_backends,
)
from .label_reader import LabelReader, get_label_reader, health, unload
from .ocr_local import LocalPaddleOCRBackend
from .paddleocr import PaddleOCRBackend

__all__ = [
    "OCRBackend",
    "OCRCancelledError",
    "OCRResult",
    "DEFAULT_PRIORITY",
    "LabelReader",
    "LocalPaddleOCRBackend",
    "PaddleOCRBackend",
    "build_backends",
    "extract_text_with_chain",
    "get_label_reader",
    "health",
    "list_configured_backends",
    "unload",
]

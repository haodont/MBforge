"""PDF molecule extraction package.

The package keeps the historical ``mbforge.pipeline.detection.extraction``
entry points while separating coordination, rendering, page detection,
configuration, and crop processing by lifecycle.
"""

from .config import (
    DEFAULT_RENDER_DPI,
    DEFAULT_TEXT_PAGE_CHAR_THRESHOLD,
    ExtractionConfig,
    load_extraction_config,
)
from .coordinator import (
    DEFAULT_SCRIBE_BATCH_SIZE,
    MAX_SCRIBE_BATCH_SIZE,
    _clamp_scribe_batch_size,
    _nearby_page_text,
    candidate_id,
    extract_molecules_from_pdf,
    extract_molecules_from_pdf_async,
    extract_molecules_from_text,
    extract_molecules_from_text_async,
)
from .crop_processor import (
    CropProcessor,
    MolParserBatcher,
    PreparedCrop,
    clamp_scribe_batch_size,
    fill_ocr_slot,
    ocr_label_image,
)
from .page_detector import PageDetector
from .page_renderer import PageRenderer

__all__ = [
    "CropProcessor",
    "DEFAULT_RENDER_DPI",
    "DEFAULT_SCRIBE_BATCH_SIZE",
    "DEFAULT_TEXT_PAGE_CHAR_THRESHOLD",
    "ExtractionConfig",
    "MAX_SCRIBE_BATCH_SIZE",
    "MolParserBatcher",
    "PageDetector",
    "PageRenderer",
    "PreparedCrop",
    "_clamp_scribe_batch_size",
    "_nearby_page_text",
    "clamp_scribe_batch_size",
    "extract_molecules_from_pdf",
    "extract_molecules_from_pdf_async",
    "extract_molecules_from_text",
    "extract_molecules_from_text_async",
    "fill_ocr_slot",
    "load_extraction_config",
    "candidate_id",
    "ocr_label_image",
]

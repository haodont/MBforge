"""The molecule pass: PDF pages in, molecule observations out.

The public surface is deliberately small — one entry point pair, the settings
the pass reads, and the records its stages exchange. The stages themselves
(renderer, detector, crop worker) are wiring details of the coordinator.

Stage-by-stage layout is documented in :mod:``coordinator``.
"""

from mbforge.service.pipeline.detection.extraction.config import (
    DEFAULT_MOLPARSER_BATCH_SIZE,
    DEFAULT_RENDER_DPI,
    DEFAULT_TEXT_PAGE_CHAR_THRESHOLD,
    MAX_MOLPARSER_BATCH_SIZE,
    ExtractionConfig,
    clamp_molparser_batch_size,
    load_extraction_config,
)
from mbforge.service.pipeline.detection.extraction.coordinator import (
    extract_molecules_from_pdf,
    extract_molecules_from_pdf_async,
)
from mbforge.service.pipeline.detection.extraction.nearby_text import nearby_block_text
from mbforge.service.pipeline.detection.extraction.records import (
    DetectedPage,
    RenderedPage,
)

__all__ = [
    "DEFAULT_MOLPARSER_BATCH_SIZE",
    "DEFAULT_RENDER_DPI",
    "DEFAULT_TEXT_PAGE_CHAR_THRESHOLD",
    "MAX_MOLPARSER_BATCH_SIZE",
    "DetectedPage",
    "ExtractionConfig",
    "RenderedPage",
    "clamp_molparser_batch_size",
    "extract_molecules_from_pdf",
    "extract_molecules_from_pdf_async",
    "load_extraction_config",
    "nearby_block_text",
]

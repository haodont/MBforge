"""Configuration values for PDF molecule extraction."""

from __future__ import annotations

from dataclasses import dataclass

from .crop_processor import (
    DEFAULT_SCRIBE_BATCH_SIZE,
    clamp_scribe_batch_size,
)

DEFAULT_RENDER_DPI = 200.0
DEFAULT_TEXT_PAGE_CHAR_THRESHOLD = 500


@dataclass(frozen=True)
class ExtractionConfig:
    """Validated runtime settings used by the page extraction coordinator."""

    render_dpi: float = DEFAULT_RENDER_DPI
    detection_batch_size: int = 0
    text_page_char_threshold: int = DEFAULT_TEXT_PAGE_CHAR_THRESHOLD
    max_pages: int | None = None
    scribe_batch_size: int = DEFAULT_SCRIBE_BATCH_SIZE


def load_extraction_config() -> ExtractionConfig:
    """Load extraction settings, falling back to safe local defaults."""
    try:
        from mbforge.utils.config import load_global_config

        config = load_global_config().moldet
        return ExtractionConfig(
            render_dpi=float(config.detection_dpi),
            detection_batch_size=int(config.detection_batch_size),
            text_page_char_threshold=int(config.text_page_char_threshold),
            max_pages=config.max_pages_per_doc,
            scribe_batch_size=clamp_scribe_batch_size(int(config.molparser_batch_size)),
        )
    except Exception:
        return ExtractionConfig()

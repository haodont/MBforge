"""Validated runtime settings for the molecule pass.

This module owns the pass's defaults and the bounds a configured value is
clamped to. It deliberately imports nothing from the stage modules: the stages
read their settings from here, not the other way round.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Render resolution for the MolDet page images, in DPI.
DEFAULT_RENDER_DPI = 200.0
#: A page with this many native characters and no images is treated as text
#: only and skipped, so MolDet never runs on prose.
DEFAULT_TEXT_PAGE_CHAR_THRESHOLD = 500
#: MolParser crops per inference batch when settings cannot be read. The
#: recognizer resizes every crop to a fixed 224x224, so its cost is per crop and
#: only amortizes with batch size; measured on a 23-page patent (63 crops,
#: RTX 3070 Ti) the molecule pass took 10.8s at 16 crops and 6.6s at 64.
DEFAULT_MOLPARSER_BATCH_SIZE = 64
#: Largest MolParser batch a configured value may request. Above this the batch
#: keeps more crop images open without a measured throughput gain.
MAX_MOLPARSER_BATCH_SIZE = 64


def clamp_molparser_batch_size(configured: int) -> int:
    """Clamp a configured MolParser batch size into its supported range."""
    return max(1, min(configured, MAX_MOLPARSER_BATCH_SIZE))


@dataclass(frozen=True)
class ExtractionConfig:
    """Validated runtime settings used by the molecule pass."""

    render_dpi: float = DEFAULT_RENDER_DPI
    detection_batch_size: int = 0
    text_page_char_threshold: int = DEFAULT_TEXT_PAGE_CHAR_THRESHOLD
    max_pages: int | None = None
    molparser_batch_size: int = DEFAULT_MOLPARSER_BATCH_SIZE


def load_extraction_config() -> ExtractionConfig:
    """Load extraction settings, falling back to safe local defaults."""
    try:
        from mbforge.foundation.config import load_global_config

        moldet = load_global_config().moldet
        return ExtractionConfig(
            render_dpi=float(moldet.detection_dpi),
            detection_batch_size=int(moldet.detection_batch_size),
            text_page_char_threshold=int(moldet.text_page_char_threshold),
            max_pages=moldet.max_pages_per_doc,
            molparser_batch_size=clamp_molparser_batch_size(
                int(moldet.molparser_batch_size)
            ),
        )
    except Exception:
        return ExtractionConfig()

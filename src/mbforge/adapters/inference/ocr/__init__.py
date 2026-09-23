"""Local OCR readers — no provider chain, nothing remote.

Page text comes from ``page_text`` (RapidOCR over the layout detector's own
text regions); ``crop_labels`` / ``label_reader`` only enrich molecule
detection. The cloud OCR backends and their fallback chain were removed: the
layout producer is the sole source of page text.
"""

from mbforge.adapters.inference.ocr.label_reader import (
    LabelReader,
    get_label_reader,
    health,
    unload,
)

__all__ = [
    "LabelReader",
    "get_label_reader",
    "health",
    "unload",
]

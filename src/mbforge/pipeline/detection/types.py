"""Re-export shim for the detection record dataclasses.

The canonical home is :mod:`mbforge.core.detection.types` (pure value
objects shared across layers). This module keeps the historical
``mbforge.pipeline.detection.types`` import path working for the pipeline
and its tests; new code should import from ``mbforge.core.detection``.
"""

from __future__ import annotations

from ...core.detection.types import (
    DetectionSource,
    ExtractionResult,
    NormalizedMolecule,
    strip_esmiles_tags,
)

__all__ = [
    "DetectionSource",
    "ExtractionResult",
    "NormalizedMolecule",
    "strip_esmiles_tags",
]

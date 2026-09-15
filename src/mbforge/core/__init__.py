"""MBForge core — domain entities and shared value objects.

Convenience re-export of the stable public domain surface so callers can
``from mbforge.core import Molecule, SourceEvidence``.  Function-heavy
helpers (parser, coverage, enumeration, provenance, stage runner) stay in
their own modules and are NOT re-exported here to avoid widening the
public namespace with generic names.
"""

from __future__ import annotations

from .activity import (
    ActivityMeasurement,
    AssayMethod,
    MeasurementValue,
    assay_method_id,
    measurement_id,
)
from .document import Document
from .evidence import SourceEvidence
from .molecule import (
    MarkushFragment,
    MarkushScaffold,
    Molecule,
    molecule_id,
)
from .patent import CompoundEntry, entry_id
from .review import ReviewDecision, ReviewState
from .types import DetectionSource, ExtractionResult

__all__ = [
    "ActivityMeasurement",
    "AssayMethod",
    "CompoundEntry",
    "DetectionSource",
    "Document",
    "ExtractionResult",
    "MarkushFragment",
    "MarkushScaffold",
    "MeasurementValue",
    "Molecule",
    "ReviewDecision",
    "ReviewState",
    "SourceEvidence",
    "assay_method_id",
    "entry_id",
    "measurement_id",
    "molecule_id",
]

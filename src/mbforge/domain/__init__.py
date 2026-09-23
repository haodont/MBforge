"""MBForge core — domain entities and shared value objects.

Convenience re-export of the stable public domain surface so callers can
``from mbforge.domain import Molecule, SourceEvidence``.  Function-heavy
helpers (parser, coverage, enumeration, provenance, stage runner) stay in
their own modules and are NOT re-exported here to avoid widening the
public namespace with generic names.
"""

from __future__ import annotations

from mbforge.domain.activity import (
    ActivityMeasurement,
    AssayMethod,
    MeasurementValue,
    assay_method_id,
    measurement_id,
)
from mbforge.domain.document import Document
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.molecule import (
    MarkushFragment,
    MarkushScaffold,
    Molecule,
    molecule_id,
)
from mbforge.domain.patent import CompoundEntry, entry_id
from mbforge.domain.review import ReviewDecision, ReviewState
from mbforge.domain.types import DetectionSource, ExtractionResult

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

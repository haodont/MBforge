"""A compound number the OCR read with the wrong letter.

The contract under test is
``mbforge.service.pipeline.patent.association._reconcile_ocr_designations``: a
capital ``I`` is read as a digit ``1`` often enough that a whole series of
compounds (``I-32``…``I-66``) reaches the library as ``1-32``…``1-66`` and no
longer matches the activity table that prints ``I-…``. The document's own
designations settle it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mbforge.service.pipeline.patent.association import (
    _reconcile_ocr_designations,
)


@dataclass
class _Candidate:
    """The shape of a recognized structure candidate."""

    name: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


def _candidate(name: str) -> _Candidate:
    return _Candidate(
        name=name,
        properties={
            "detection_names": [name],
            "name_candidates": [{"name": name, "confidence": 0.9, "source": "crop"}],
        },
    )


def test_a_misread_series_letter_takes_the_documents_spelling() -> None:
    """``1-256-A`` is the document's ``I-256-A``.

    The document prints the compound in its activity table and in its example
    heading; the OCR read the drawing's caption with a digit. The document's
    spelling is the compound's.
    """
    candidate = _candidate("1-256-A")
    entries = [{"label_key": "I-256-A", "label_raw": "I-256-A"}]
    measurements = [
        {
            "provenance": {
                "reference_key": "I-256-A",
                "reference_raw": "I-256-A",
            }
        }
    ]
    issues: list[dict[str, Any]] = []

    reconciled = _reconcile_ocr_designations([candidate], entries, measurements, issues)

    assert reconciled == 1
    assert candidate.name == "I-256-A"
    assert candidate.properties["detection_names"] == ["I-256-A"]
    assert candidate.properties["name_candidates"][0]["name"] == "I-256-A"
    assert [issue["code"] for issue in issues] == ["designation_ocr_reconciled"]


def test_a_number_the_document_prints_is_left_alone() -> None:
    """A designation the document prints keeps its own spelling."""
    candidate = _candidate("1-280")
    entries = [{"label_key": "1-280", "label_raw": "1-280"}]
    issues: list[dict[str, Any]] = []

    reconciled = _reconcile_ocr_designations([candidate], entries, [], issues)

    assert reconciled == 0
    assert candidate.name == "1-280"
    assert issues == []


def test_an_ambiguous_confusion_is_not_reconciled() -> None:
    """When the document prints both spellings, neither is chosen."""
    candidate = _candidate("1-32")
    entries = [
        {"label_key": "1-32", "label_raw": "1-32"},
        {"label_key": "I-32", "label_raw": "I-32"},
    ]
    issues: list[dict[str, Any]] = []

    reconciled = _reconcile_ocr_designations([candidate], entries, [], issues)

    assert reconciled == 0
    assert candidate.name == "1-32"
    assert issues == []

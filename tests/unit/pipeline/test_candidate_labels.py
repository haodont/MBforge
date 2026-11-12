"""Which printed designations a recognized structure candidate answers to.

A candidate carries its designations through several channels: the crop-label
OCR, a normalized coreference label, the formula header, its ``name`` and the
``labels`` column (every designation its drawings printed). A structure whose
printed number never won the name is still that compound, and a rule that
reads only the name cannot see it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mbforge.service.pipeline.patent.candidate_labels import (
    candidate_label_keys,
    candidate_owns_designation,
)


@dataclass
class _Candidate:
    """The shape the candidate readers see: a molecule row."""

    name: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)


def test_a_drawing_printed_designation_answers_to_its_own_label() -> None:
    """The labels column is a designation channel, not decoration.

    The compound is printed twice; neither copy kept the number as its name,
    but both drawings printed it. Without the labels channel the structure
    answers to no designation at all, and every reading that cites it stays
    unowned.
    """
    candidate = _Candidate(
        name="",
        properties={"ocr_labels_unassigned": ["13"]},
        labels=["13"],
    )

    assert candidate_label_keys(candidate) == {"13"}


def test_candidate_keys_merge_every_channel() -> None:
    """Properties, name and labels are read together."""
    candidate = _Candidate(
        name="29",
        properties={"ocr_labels": ["30"]},
        labels=["31"],
    )

    assert candidate_label_keys(candidate) == {"29", "30", "31"}


def test_a_name_that_is_not_a_designation_stays_out() -> None:
    """A printed chemistry name yields no key, so no association is invented."""
    candidate = _Candidate(name="N-(3-((6-氯-2-甲基喹啉-4-基)氨基)环己烷)", labels=[])

    assert candidate_label_keys(candidate) == set()


def test_ownership_is_decided_by_the_drawings_that_agree() -> None:
    """Reading one more channel does not change who owns a designation."""
    candidate = _Candidate(
        name="",
        properties={
            "detection_designations": [
                {"name": "13"},
                {"name": "13"},
                {"name": "14"},
            ]
        },
        labels=["13", "14"],
    )

    assert candidate_owns_designation(candidate, "13") is True
    assert candidate_owns_designation(candidate, "14") is False

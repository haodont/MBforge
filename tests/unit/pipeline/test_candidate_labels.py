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
    candidate_example_keys,
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


def test_an_example_captioned_drawing_answers_to_its_example_identity() -> None:
    """A drawing captioned ``实施例19`` is not compound 19 — but it is not nothing.

    The page-text naming pass stores the key it matched, so the structure's name
    is ``@example:19``. The compound key space stays clean (no ``19`` is
    invented), while the example identity reaches the drawing that was printed
    under its own heading.
    """
    stored = _Candidate(name="@example:19")
    printed = _Candidate(name="实施例 19")

    assert candidate_label_keys(stored) == set()
    assert candidate_label_keys(printed) == set()
    assert candidate_example_keys(stored) == {"@example:19"}
    assert candidate_example_keys(printed) == {"@example:19"}
    assert candidate_owns_designation(stored, "@example:19") is True


def test_a_digit_headed_series_label_answers_to_the_lettered_spelling() -> None:
    """``1-256-A`` and ``I-256-A`` name one compound in a CN series.

    The layout reads the series head ``I`` as the digit ``1`` often enough that a
    drawing is captioned ``1-256-A`` while the activity table cites ``I-256-A``
    (CN121717757A p137). Neither the digit form being an invalid designation nor
    the two spellings being distinct keys may strand that reading: the drawing
    answers to both, and a bare number or a chemistry name still gains nothing.
    """
    candidate = _Candidate(name="1-256-A", labels=["1-256-A"])

    keys = candidate_label_keys(candidate)

    assert "1-256-A" in keys
    assert "I-256-A" in keys
    # A stereochemical prefix keeps its own key and gains no series variant.
    assert "cis-I-278" not in candidate_label_keys(_Candidate(name="I-255-A"))
    assert "1" not in {key for key in keys if key != "1-256-A"}


def test_a_tally_in_the_other_spelling_still_owns_the_designation() -> None:
    """The page prints ``1-2``; the activity table asks for ``I-2``.

    The per-drawing tally holds the spelling the page printed, so a literal read of
    it says the structure owns nothing and every reading that cited either spelling
    stays unowned — measured on CN121717757A's I-2, whose drawing tallies
    ``{1-2: 2, 1-1: 1, 7-1: 1}`` and answered ``owns: false``.
    """
    candidate = _Candidate(
        name="1-1",
        properties={
            "detection_designations": [
                {"name": "1-2"},
                {"name": "1-2"},
                {"name": "1-1"},
                {"name": "7-1"},
            ]
        },
    )

    assert candidate_owns_designation(candidate, "I-2") is True
    assert candidate_owns_designation(candidate, "1-2") is True
    # A designation outvoted by its own drawings is still not owned, in either
    # spelling: 7-1 appears once while 1-2 appears twice.
    assert candidate_owns_designation(candidate, "7-1") is False
    assert candidate_owns_designation(candidate, "I-7-1") is False

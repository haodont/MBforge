"""Unbound readings become review items, and a human decision binds them.

Functions under test: ``_queue_unbound_readings`` and the
``designation_unbound`` decision path in ``review_queue.decide``.

This is the bridge that lets a printed reading with no structure reach the
review center (and the AI assist/proposal flow) instead of staying a silent
attribution gap.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.contracts.measurement import (
    DESIGNATION_UNBOUND_KIND,
    MeasurementRecord,
)
from mbforge.db import measurement_store
from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.patent_facts import _queue_unbound_readings
from mbforge.service.use_cases.review_queue import decide_items

DOC = "doc1"


class _Detection:
    def __init__(
        self,
        page: int,
        bbox: tuple[float, float, float, float] | None = None,
        image_path: str | None = None,
    ) -> None:
        self.page = page
        self.bbox = bbox
        self.image_path = image_path


class _Candidate:
    def __init__(
        self,
        smiles: str,
        name: str,
        page0: int,
        bbox: tuple[float, float, float, float] | None = None,
        image_path: str | None = None,
    ) -> None:
        self.canonical_smiles = smiles
        self.smiles = smiles
        self.name = name
        # The publication pass classifies unclassified candidates, so the stub
        # has to look like a molecule record (role, not just smiles).
        self.status = "pending"
        self.properties = {}
        self.labels = []
        self.detections = [_Detection(page0, bbox, image_path)]


class _Decision:
    def __init__(self, item_id: str, choice: str | None = None) -> None:
        self.kind = DESIGNATION_UNBOUND_KIND
        self.id = item_id
        self.choice = choice
        self.expected_revision = None


def _artifact() -> PatentFactsArtifact:
    return PatentFactsArtifact(
        doc_id=DOC,
        run_id="run-1",
        entries=[],
        measurements=[
            {
                "measurement_id": "m-unbound",
                "page_num": 3,
                "compound_entry_id": "entry-1",
                "mol_id": None,
                "metric": "IC50",
                "raw_text": "53.7",
                "evidence_ids": ["ev-reading"],
                "value": {"original_value": 53.7, "original_unit": "nM"},
                "provenance": {"reference_key": "11", "reference_type": "compound"},
            },
            {
                "measurement_id": "m-bound",
                "page_num": 3,
                "mol_id": "CCO",
                "provenance": {"reference_key": "2", "reference_type": "compound"},
            },
        ],
    )


def test_a_reading_with_drawn_candidates_becomes_a_review_item(tmp_path: Path) -> None:
    review = get_repositories(str(tmp_path)).review
    queued = _queue_unbound_readings(
        review,
        DOC,
        _artifact(),
        [
            _Candidate(
                "CCOc1ccccc1",
                "11",
                page0=2,
                bbox=(10, 20, 30, 40),
                image_path="storage/doc1/crops/mol-11.png",
            ),
            _Candidate("CCNc1ccccc1", "", page0=2),
        ],
    )

    assert queued == 1  # only the unbound reading; the bound one is skipped
    item = get_repositories(str(tmp_path)).review.get_item(
        DESIGNATION_UNBOUND_KIND,
        review.list_queue(kind=DESIGNATION_UNBOUND_KIND)[0][0]["id"],
    )
    assert item["page"] == 3
    assert item["payload"]["measurement_id"] == "m-unbound"
    assert item["payload"]["designation"] == "11"
    assert [candidate["mol_id"] for candidate in item["payload"]["candidates"]] == [
        "CCOc1ccccc1",
        "CCNc1ccccc1",
    ]
    # A reviewer can only confirm a structure they can see, so each candidate
    # must carry the location of its own drawing.
    first = item["payload"]["candidates"][0]
    assert first["page"] == 3  # 1-based, from page0=2
    assert first["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert first["crop_relpath"] == "storage/doc1/crops/mol-11.png"


def test_a_reading_with_no_drawn_structure_is_not_queued(tmp_path: Path) -> None:
    review = get_repositories(str(tmp_path)).review

    queued = _queue_unbound_readings(review, DOC, _artifact(), [])

    assert queued == 0
    assert review.list_queue(kind=DESIGNATION_UNBOUND_KIND)[1] == 0


def test_confirming_the_choice_writes_a_human_attribution(
    tmp_path: Path, patch_config_root
) -> None:
    patch_config_root(tmp_path)
    measurement_store.replace_document_measurements(
        tmp_path,
        DOC,
        [
            MeasurementRecord(
                measurement_id="m-unbound",
                doc_id=DOC,
                page_num=3,
                metric="IC50",
                original_value=53.7,
                original_unit="nM",
            )
        ],
    )
    review = get_repositories(str(tmp_path)).review
    review.insert_review_item(
        item_id="unbound-1",
        kind=DESIGNATION_UNBOUND_KIND,
        doc_id=DOC,
        page=3,
        name="11",
        reasons=["designation_without_structure"],
        payload={
            "doc_id": DOC,
            "measurement_id": "m-unbound",
            "designation": "11",
            "evidence_ids": ["ev-reading"],
            "candidates": [{"mol_id": "CCOc1ccccc1", "smiles": "CCOc1ccccc1"}],
        },
    )

    decided = decide_items(
        str(tmp_path),
        "confirm",
        "the printed row is compound 11",
        [_Decision("unbound-1", "CCOc1ccccc1")],
    )

    assert decided.updated == 1
    assert decided.results[0]["applied"] is True
    links = get_repositories(str(tmp_path)).measurements.attributions_for(["m-unbound"])
    assert links["m-unbound"][0]["mol_id"] == "CCOc1ccccc1"
    assert links["m-unbound"][0]["method"] == "human"
    assert links["m-unbound"][0]["review_status"] == "accepted"


def test_a_choice_outside_the_candidates_is_refused(
    tmp_path: Path, patch_config_root
) -> None:
    patch_config_root(tmp_path)
    review = get_repositories(str(tmp_path)).review
    review.insert_review_item(
        item_id="unbound-2",
        kind=DESIGNATION_UNBOUND_KIND,
        doc_id=DOC,
        page=3,
        reasons=["designation_without_structure"],
        payload={
            "doc_id": DOC,
            "measurement_id": "m-2",
            "candidates": [{"mol_id": "CCO", "smiles": "CCO"}],
        },
    )

    decided = decide_items(
        str(tmp_path), "confirm", "", [_Decision("unbound-2", "CCN")]
    )

    assert decided.updated == 0 and decided.skipped == 1
    assert "not one of the printed candidates" in decided.results[0]["error"]

"""Human decisions on contested Patent facts (P3).

Protects the review loop the plan requires: a published conflict becomes one
review item, a decision needs an explicit choice, confirming adopts exactly one
reading (or neither), reopening restores the review, a stale revision is refused
instead of overwriting newer facts, and a decision survives a re-run only while
its candidate set and evidence set still match.

Functions under test: ``publish_document_facts``
(``mbforge.service.use_cases.documents.patent_facts``), ``decide`` /
``queue_page`` (``mbforge.service.use_cases.review_queue``) and
``apply_decisions`` (``mbforge.service.pipeline.patent.decisions``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mbforge.contracts.patent import PatentDraft
from mbforge.domain.review import (
    ReviewConflictError,
    ReviewTransitionError,
)
from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.service.pipeline.patent.decisions import apply_decisions
from mbforge.service.pipeline.patent.llm_merge import merge_submission
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.patent_facts import (
    load_patent_facts,
    publish_document_facts,
)
from mbforge.service.use_cases.review_queue import decide, queue_page

DOC = "doc-1"
KIND = "patent_fact_review"


@pytest.fixture(autouse=True)
def _configured_library(tmp_path: Path, patch_config_root: Any) -> None:
    """Point the configured library at the test's temp root, as production does."""
    patch_config_root(tmp_path)


def _rule_measurement(*, value: float = 10.0) -> dict[str, Any]:
    return {
        "measurement_id": "m-1",
        "doc_id": DOC,
        "compound_entry_id": "entry-1",
        "assay_method_id": "assay-1",
        "mol_id": None,
        "metric": "IC50",
        "linking_status": "linked",
        "value": {
            "raw_text": f"IC50 = {value:g} nM",
            "operator": "=",
            "original_value": value,
            "original_unit": "nM",
            "canonical_value": None,
            "canonical_unit": "",
            "qualitative_value": "",
        },
        "evidence_ids": ["ev-1"],
        "provenance": {"reference_raw": "1", "reference_key": "1"},
    }


def _merge(*, llm_value: float) -> Any:
    submission = PatentDraft.model_validate(
        {
            "protocol_version": "1",
            "doc_id": DOC,
            "attempt_id": "attempt-1",
            "evidence_signature": "sig-1",
            "assay_methods": [],
            "measurements": [
                {
                    "local_key": "measurement-1",
                    "metric": "IC50",
                    "value": {
                        "raw_text": f"IC50 = {llm_value:g} nM",
                        "operator": "=",
                        "value": llm_value,
                        "unit": "nM",
                    },
                    "compound_label_raw": "Compound 1",
                    "compound_label_key": "1",
                    "page": 7,
                    "evidence_ids": ["ev-1"],
                }
            ],
            "associations": [],
            "coverage": {"pages_viewed": [1], "pages_uncovered": []},
        }
    )
    return merge_submission(
        doc_id=DOC,
        rule_measurements=[_rule_measurement()],
        rule_assay_methods=[
            {
                "assay_method_id": "assay-1",
                "doc_id": DOC,
                "target": "MRGPRX2",
                "system": "human",
                "endpoint": "calcium flux",
                "evidence_ids": ["ev-1"],
            }
        ],
        submission=submission,
        evidence_pages={"ev-1": 7},
    )


def _artifact(merge: Any) -> PatentFactsArtifact:
    candidates = [
        {
            **{key: value for key, value in candidate.items() if key != "conflict"},
            "conflict": candidate["conflict"].model_dump(),
        }
        for candidate in merge.candidates
    ]
    return PatentFactsArtifact.model_validate(
        {
            "doc_id": DOC,
            "run_id": "run-1",
            "entries": [],
            "measurements": merge.measurements,
            "analysis_status": "succeeded",
            "extraction_mode": "hybrid",
            "conflicts": [conflict.model_dump() for conflict in merge.conflicts],
            "review_candidates": candidates,
        }
    )


def _publish(root: Path, merge: Any):
    return publish_document_facts(
        root,
        doc_id=DOC,
        artifact=_artifact(merge),
        evidence_signature="sig-1",
    )


def _item_id(root: Path) -> str:
    items, total = get_repositories(root).review.list_queue(
        kind=KIND, status=None, doc_id=None, page=1, page_size=10
    )
    assert total == 1
    return items[0]["id"]


def test_a_conflict_becomes_one_item_and_only_an_explicit_choice_adopts(
    tmp_path: Path, patch_config_root: Any
) -> None:
    """Publication upserts the item; confirming without a choice, rejecting and a
    stale revision are all refused without adopting anything."""
    item_root = tmp_path / "item"
    patch_config_root(item_root)
    _publish(item_root, _merge(llm_value=100.0))

    item_id = _item_id(item_root)
    row = get_repositories(item_root).review.review_item_status_payload(item_id, KIND)
    assert row is not None
    assert row["payload"]["doc_id"] == DOC
    assert row["payload"]["slot_id"]
    assert row["payload"]["revision"] == 1

    # A re-run upserts the same item instead of duplicating it.
    _publish(item_root, _merge(llm_value=100.0))
    _, total = get_repositories(item_root).review.list_queue(
        kind=KIND, status=None, doc_id=None, page=1, page_size=10
    )
    assert total == 1

    no_choice_root = tmp_path / "no-choice"
    patch_config_root(no_choice_root)
    _publish(no_choice_root, _merge(llm_value=100.0))

    with pytest.raises(ReviewTransitionError):
        decide(
            get_repositories(no_choice_root).review,
            kind=KIND,
            item_id=_item_id(no_choice_root),
            action="confirm",
            choice=None,
            library_root=str(no_choice_root),
        )

    no_choice_facts = load_patent_facts(no_choice_root, DOC)
    assert no_choice_facts is not None
    assert no_choice_facts.measurements == []  # still contested, nothing adopted

    rejected_root = tmp_path / "rejected"
    patch_config_root(rejected_root)
    _publish(rejected_root, _merge(llm_value=100.0))

    rejected = decide(
        get_repositories(rejected_root).review,
        kind=KIND,
        item_id=_item_id(rejected_root),
        action="reject",
        library_root=str(rejected_root),
    )

    assert rejected["status"] == "rejected"
    rejected_facts = load_patent_facts(rejected_root, DOC)
    assert rejected_facts is not None
    assert rejected_facts.measurements == []

    stale_root = tmp_path / "stale"
    patch_config_root(stale_root)
    _publish(stale_root, _merge(llm_value=100.0))
    _publish(stale_root, _merge(llm_value=100.0))  # revision 2

    with pytest.raises(ReviewConflictError):
        decide(
            get_repositories(stale_root).review,
            kind=KIND,
            item_id=_item_id(stale_root),
            action="confirm",
            choice="deterministic",
            expected_revision=1,
            library_root=str(stale_root),
        )


def test_confirming_and_reopening_an_adopted_slot(tmp_path: Path) -> None:
    _publish(tmp_path, _merge(llm_value=100.0))
    review = get_repositories(tmp_path).review
    item_id = _item_id(tmp_path)

    result = decide(
        review,
        kind=KIND,
        item_id=item_id,
        action="confirm",
        choice="llm",
        expected_revision=1,
        library_root=str(tmp_path),
    )

    assert result["status"] == "confirmed"
    assert result["revision"] == 2
    facts = load_patent_facts(tmp_path, DOC)
    assert facts is not None
    assert len(facts.measurements) == 1
    measurement = facts.measurements[0]
    assert measurement["value"]["original_value"] == 100.0
    assert measurement["provenance"]["source"] == "llm"
    # The slot is resolved: it is neither contested nor pending any more.
    assert facts.conflicts == []
    assert facts.review_candidates == []
    state = get_repositories(tmp_path).patent_analysis.load(DOC)
    assert state is not None
    assert len(state["decisions"]) == 1
    assert list(state["decisions"].values())[0]["choice"] == "llm"
    _, pending = review.list_queue(
        kind=KIND, status="pending", doc_id=DOC, page=1, page_size=10
    )
    assert pending == 0

    confirmed = queue_page(str(tmp_path), KIND, "confirmed", DOC, 1, 10)
    assert confirmed.items[0].payload["revision"] == 2

    reopened = decide(
        review,
        kind=KIND,
        item_id=item_id,
        action="reopen",
        expected_revision=confirmed.items[0].payload["revision"],
        library_root=str(tmp_path),
    )

    assert reopened["status"] == "pending"
    reopened_facts = load_patent_facts(tmp_path, DOC)
    assert reopened_facts is not None
    assert reopened_facts.measurements == []
    assert len(reopened_facts.conflicts) == len(reopened_facts.review_candidates) == 1
    rows, reopened_pending = review.list_queue(
        kind=KIND, status="pending", doc_id=DOC, page=1, page_size=10
    )
    assert reopened_pending == 1
    assert rows[0]["payload"]["revision"] == 3


def test_a_decision_is_reused_only_while_the_candidate_set_matches(
    tmp_path: Path,
) -> None:
    _publish(tmp_path, _merge(llm_value=100.0))
    decide(
        get_repositories(tmp_path).review,
        kind=KIND,
        item_id=_item_id(tmp_path),
        action="confirm",
        choice="llm",
        library_root=str(tmp_path),
    )

    # Same facts again: the stored decision is re-applied automatically.
    _publish(tmp_path, _merge(llm_value=100.0))
    facts = load_patent_facts(tmp_path, DOC)
    assert facts is not None
    assert [item["value"]["original_value"] for item in facts.measurements] == [100.0]

    # Changed candidate set: the decision no longer describes these facts.
    _publish(tmp_path, _merge(llm_value=150.0))
    facts = load_patent_facts(tmp_path, DOC)
    assert facts is not None
    assert facts.measurements == []
    assert facts.conflicts  # contested again, awaiting a fresh decision
    state = get_repositories(tmp_path).patent_analysis.load(DOC)
    assert state is not None
    assert state["decisions"] == {}

    # The pure core: a decision with a different signature is not applied.
    merge = _merge(llm_value=100.0)
    conflict = merge.conflicts[0]
    stale = apply_decisions(
        doc_id=DOC,
        measurements=[],
        candidates=[],
        conflicts=[conflict],
        decisions={
            conflict.slot_id: {
                "choice": "llm",
                "candidate_set_signature": "not-the-current-set",
                "evidence_signature": "sig-1",
            }
        },
        evidence_signature="sig-1",
    )
    assert stale.applied == []
    assert stale.stale == [conflict.slot_id]
    assert stale.measurements == []

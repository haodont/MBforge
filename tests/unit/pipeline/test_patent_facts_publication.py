"""Publication, revision and projection consistency for Patent facts (P3).

Protects: one transaction commits the snapshot and the derived rows, a stale
caller is refused instead of overwriting newer facts, the file projection always
carries the committed revision, reads prefer the snapshot over a stale file and
repair it, a failed projection is reported and repaired, and publishing empty or
partial facts never deletes the structures Extract stored.

Functions under test: ``publish_document_facts`` / ``load_patent_facts``
(``mbforge.service.use_cases.documents.patent_facts``), ``read_patent_facts`` /
``LibraryStore`` (``mbforge.service.use_cases.documents.library``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource
from mbforge.foundation.errors import ConflictError
from mbforge.foundation.layout import LibraryLayout
from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.library import read_patent_facts
from mbforge.service.use_cases.documents.patent_facts import (
    load_patent_facts,
    publish_document_facts,
)

DOC = "doc-1"


def _artifact(**overrides: Any) -> PatentFactsArtifact:
    payload: dict[str, Any] = {
        "doc_id": DOC,
        "run_id": "run-1",
        "entries": [],
        "measurements": [],
    }
    payload.update(overrides)
    return PatentFactsArtifact.model_validate(payload)


def _publish(root: Path, artifact: PatentFactsArtifact, **kwargs: Any):
    return publish_document_facts(
        root,
        doc_id=DOC,
        artifact=artifact,
        evidence_signature=kwargs.pop("evidence_signature", "sig-1"),
        **kwargs,
    )


def _boom(*_args: Any, **_kwargs: Any) -> None:
    raise OSError("disk full")


def test_each_publication_bumps_the_revision_and_refuses_a_stale_caller(
    tmp_path: Path,
) -> None:
    first = _publish(tmp_path, _artifact())
    second = _publish(
        tmp_path, _artifact(entries=[{"entry_id": "e-1", "label_key": "1"}])
    )

    assert (first.revision, second.revision) == (1, 2)
    assert second.projection_ok is True

    on_disk = json.loads(
        LibraryLayout(tmp_path).patent_facts_json(DOC).read_text(encoding="utf-8")
    )
    assert on_disk["revision"] == 2
    state = get_repositories(tmp_path).patent_analysis.load(DOC)
    assert state is not None
    assert state["revision"] == 2
    assert state["evidence_signature"] == "sig-1"

    stale_root = tmp_path / "stale"
    _publish(stale_root, _artifact())

    with pytest.raises(ConflictError):
        _publish(stale_root, _artifact(), expected_revision=7)

    stale_state = get_repositories(stale_root).patent_analysis.load(DOC)
    assert stale_state is not None
    assert stale_state["revision"] == 1


def test_reads_prefer_the_snapshot_and_repair_a_failed_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(tmp_path, _artifact(entries=[{"entry_id": "e-1", "label_key": "1"}]))
    path = LibraryLayout(tmp_path).patent_facts_json(DOC)
    path.write_text(
        json.dumps({"doc_id": DOC, "run_id": "tampered", "revision": 1}),
        encoding="utf-8",
    )

    facts = PatentFactsArtifact.model_validate_json(
        read_patent_facts(str(tmp_path), DOC)
    )

    assert facts is not None
    assert facts.revision == 1
    assert facts.projection_status == "current"
    assert [entry["entry_id"] for entry in facts.entries] == ["e-1"]
    assert json.loads(path.read_text(encoding="utf-8"))["revision"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "run-1"

    from mbforge.service.use_cases.documents import patent_facts as patent_facts_module

    projection_root = tmp_path / "projection"
    monkeypatch.setattr(patent_facts_module, "write_json_atomic", _boom)

    result = _publish(projection_root, _artifact())

    assert result.projection_ok is False
    assert "disk full" in str(result.projection_error)
    # The commit itself stands: SQL is authoritative, the file is a projection.
    assert result.revision == 1

    pending = load_patent_facts(projection_root, DOC)
    assert pending is not None
    assert pending.projection_status == "pending"
    assert (
        "projection_status"
        not in get_repositories(projection_root).patent_analysis.load(DOC)["payload"]
    )

    monkeypatch.undo()
    repaired = load_patent_facts(projection_root, DOC)
    assert repaired is not None
    assert repaired.revision == 1
    assert repaired.projection_status == "current"
    assert LibraryLayout(projection_root).patent_facts_json(DOC).is_file()


def test_publishing_empty_facts_keeps_the_structures_evidence_owns(
    tmp_path: Path,
) -> None:
    """An empty Patent pass must not delete structures Extract stored.

    Structure ownership moved to the Extract stage: it stores every concrete
    structure it recognizes, while the Patent stage only re-persists the handful
    it can prove a reading belongs to. Clearing the document's detections here
    therefore destroyed evidence's own rows — a 113-page patent went from 290
    stored structures to 8, and a document whose facts came out empty lost all of
    them. Re-extraction owns that cleanup (``delete_document_molecule_data``).
    """
    candidate = Molecule(
        canonical_smiles="CCO",
        smiles="CCO",
        name="Compound 1",
        properties={"structure_role": "complete"},
        detections=[
            DetectionSource(
                source="image", page=0, bbox=(0.0, 0.0, 1.0, 1.0), evidence_id="ev-1"
            )
        ],
    )
    get_repositories(tmp_path).molecules.replace_document_candidates(DOC, [candidate])

    db = DatabaseManager.get(str(tmp_path))
    with db.connection() as conn:
        seeded = conn.execute(
            "SELECT COUNT(*) AS n FROM molecule_detections WHERE doc_id = ?", (DOC,)
        ).fetchone()["n"]
    assert seeded == 1

    # No measurements at all: nothing is persistable this time.
    _publish(tmp_path, _artifact())

    with db.connection() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM molecule_detections WHERE doc_id = ?", (DOC,)
        ).fetchone()["n"]
    assert remaining == 1


def test_republishing_subset_keeps_other_structures_detections(
    tmp_path: Path,
) -> None:
    """Publishing a few facts must not delete the structures Extract stored.

    Regression: the Patent stage passes only the structures it can prove a
    reading belongs to, then cleared the document's ``molecule_detections``
    first. A 113-page patent that Extract stored 290 structures for came out
    with 8 remaining detection rows, so the library could not answer which
    structure a page drew.
    """

    def _candidate(smiles: str, page: int) -> Molecule:
        return Molecule(
            canonical_smiles=smiles,
            smiles=smiles,
            name="",
            properties={"structure_role": "complete"},
            detections=[
                DetectionSource(
                    source="image",
                    page=page,
                    bbox=(0.0, 0.0, 1.0, 1.0),
                    evidence_id=f"ev-{smiles}",
                )
            ],
        )

    # Extract stored three structures.
    get_repositories(tmp_path).molecules.replace_document_candidates(
        DOC,
        [_candidate("CCO", 1), _candidate("CCN", 2), _candidate("CCC", 3)],
    )
    db = DatabaseManager.get(str(tmp_path))
    with db.connection() as conn:
        before = conn.execute(
            "SELECT COUNT(*) AS n FROM molecule_detections WHERE doc_id = ?", (DOC,)
        ).fetchone()["n"]
    assert before == 3

    # The Patent stage can only prove one of them has a bound reading.
    get_repositories(tmp_path).molecules.replace_document_candidates(
        DOC, [_candidate("CCO", 1)]
    )

    with db.connection() as conn:
        after = conn.execute(
            "SELECT COUNT(*) AS n FROM molecule_detections WHERE doc_id = ?", (DOC,)
        ).fetchone()["n"]
    assert after == 3


def test_a_withheld_drawing_becomes_a_review_item(tmp_path) -> None:
    """The role gate's refusal must be visible, not silent.

    CN121717757A's I-2 drawing matches 实施例3's printed MS but was withheld and
    stored nowhere, so no reading could name it and no queue asked anyone to
    look. A withheld concrete structure is now an item a person can promote; a
    scaffold is still not one, because the document cannot have measured it.
    """
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.domain.molecule import Molecule
    from mbforge.domain.types import DetectionSource
    from mbforge.service.ports import get_repositories
    from mbforge.service.use_cases.documents.patent_facts import (
        _queue_withheld_structures,
    )

    DatabaseManager.get(str(tmp_path)).initialize()
    review = get_repositories(str(tmp_path)).review

    def _candidate(smiles: str, page: int) -> Molecule:
        return Molecule(
            canonical_smiles=smiles,
            esmiles=smiles,
            name="",
            status="pending",
            detections=[
                DetectionSource(source="image", page=page, bbox=(1.0, 2.0, 3.0, 4.0))
            ],
            properties={
                "structure_role": "review_required",
                "structure_role_reasons": ["context_numbered_r_group"],
            },
        )

    queued = _queue_withheld_structures(
        review,
        "doc-1",
        [
            _candidate("COc1ccc(C(=O)NC2CCCCC2)cc1", 31),
            _candidate("*c1ccccc1", 5),
        ],
    )

    assert queued == 1
    items, total = review.list_queue(kind="review_required", status="pending")
    assert total == 1
    assert items[0]["smiles"] == "COc1ccc(C(=O)NC2CCCCC2)cc1"
    assert items[0]["page"] == 32
    assert items[0]["reasons"] == ["context_numbered_r_group"]

    # A re-run does not reopen a decided item.
    item_id = items[0].get("id") or items[0]["item_id"]
    review.set_review_item_status(item_id, "review_required", "confirmed")
    _queue_withheld_structures(
        review, "doc-1", [_candidate("COc1ccc(C(=O)NC2CCCCC2)cc1", 31)]
    )
    assert review.get_item("review_required", item_id)["status"] == "confirmed"

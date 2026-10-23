"""Unit tests for the Markush review service.

The service is the persistence-side counterpart of the pipeline's
``review_required`` branch. It owns:

- ``source_key`` / ``content_hash`` derivation
- Re-import protection: same source + same content keeps human state;
  same source + different content supersedes the old row and inserts a
  fresh ``pending`` row; new source creates a new ``pending`` row.
- Appending to ``markush_evidence`` and ``markush_decisions``.

Covers ``mbforge.db.markush_candidates.persist_review_candidates`` and the
``compute_source_key`` / ``compute_content_hash`` provenance helpers.
"""

from __future__ import annotations

import json

import pytest

from mbforge.db.markush_candidates import persist_review_candidates
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.molecule import Molecule
from mbforge.domain.provenance import (
    compute_content_hash,
    compute_source_key,
)
from mbforge.domain.types import DetectionSource


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def _candidate(
    *,
    smiles: str,
    label: str | None = None,
    bbox: tuple[float, float, float, float] = (10.0, 20.0, 110.0, 220.0),
    page: int = 1,
) -> Molecule:
    molecule = Molecule(
        canonical_smiles=smiles,
        esmiles=smiles,
        name="",
        detections=[
            DetectionSource(
                source="image",
                page=page,
                bbox=bbox,
                image_path="crop.png",
                confidence=0.9,
            )
        ],
    )
    molecule.properties["structure_role"] = "review_required"
    molecule.properties["structure_role_reasons"] = ["context_formula_label"]
    if label is not None:
        molecule.properties["raw_coref_label"] = label
        molecule.properties["normalized_label"] = label
        molecule.properties["label_kind"] = "r_group"
    return molecule


def test_source_key_and_content_hash_derivation() -> None:
    """``source_key`` quantizes the bbox to 0.1 pt (OCR jitter keeps identity)
    but changes with the label; ``content_hash`` changes with the SMILES."""
    raw = compute_source_key(
        doc_id="doc-1",
        page=1,
        bbox=(10.05, 20.04, 110.07, 220.11),
        normalized_label="R1",
    )
    jittered = compute_source_key(
        doc_id="doc-1",
        page=1,
        bbox=(10.10, 20.01, 110.13, 220.09),
        normalized_label="R1",
    )
    relabelled = compute_source_key("doc-1", 1, (10.0, 20.0, 110.0, 220.0), "R2")
    assert raw == jittered
    assert raw != relabelled

    hash_a = compute_content_hash(
        canonical_smiles="*c1ccccc1",
        esmiles="*c1ccccc1",
        context="Formula I",
        recognition_version=1,
    )
    hash_b = compute_content_hash(
        canonical_smiles="*c1ccncc1",
        esmiles="*c1ccncc1",
        context="Formula I",
        recognition_version=1,
    )
    assert hash_a != hash_b


def test_persist_review_candidates_writes_row_and_decision_log(database) -> None:
    """A first-time insert lands as a ``pending`` row with its metadata and
    writes the ``candidate_created`` audit row."""
    candidates = [_candidate(smiles="*c1ccccc1", label="R1")]
    with database.mol_conn() as conn:
        inserted = persist_review_candidates(
            doc_id="doc-1",
            candidates=candidates,
            conn=conn,
            recognition_version=1,
        )
        row = conn.execute(
            "SELECT doc_id, predicted_role, normalized_label, label_kind, "
            "review_status, review_version, recognition_status "
            "FROM markush_review_candidates"
        ).fetchone()
        decision = conn.execute(
            "SELECT action, new_state, snapshot FROM markush_decisions"
        ).fetchone()

    assert inserted == 1
    assert row["doc_id"] == "doc-1"
    assert row["predicted_role"] == "review_required"
    assert row["normalized_label"] == "R1"
    assert row["label_kind"] == "r_group"
    assert row["review_status"] == "pending"
    assert row["review_version"] == 1
    assert row["recognition_status"] == "valid"

    assert decision["action"] == "candidate_created"
    assert decision["new_state"] == "pending"
    snapshot = json.loads(decision["snapshot"])
    assert snapshot["normalized_label"] == "R1"
    assert snapshot["smiles"] == "*c1ccccc1"


def test_persist_writes_evidence_per_detection(database) -> None:
    """All detections of a candidate land in ``markush_evidence``."""
    molecule = Molecule(
        canonical_smiles="*c1ccccc1",
        esmiles="*c1ccccc1",
        name="",
        detections=[
            DetectionSource(
                source="image",
                page=1,
                bbox=(10, 20, 110, 220),
                image_path="a.png",
                confidence=0.9,
            ),
            DetectionSource(
                source="image",
                page=1,
                bbox=(12, 22, 112, 222),
                image_path="b.png",
                confidence=0.85,
            ),
        ],
    )
    molecule.properties["structure_role"] = "review_required"
    molecule.properties["raw_coref_label"] = "R1"
    molecule.properties["normalized_label"] = "R1"

    with database.mol_conn() as conn:
        persist_review_candidates("doc-1", [molecule], conn=conn, recognition_version=1)

    with database.mol_conn() as conn:
        evidence_rows = conn.execute(
            "SELECT crop_relpath, page, entity_type "
            "FROM markush_evidence ORDER BY evidence_id"
        ).fetchall()
    assert len(evidence_rows) == 2
    assert {row["crop_relpath"] for row in evidence_rows} == {"a.png", "b.png"}
    assert all(row["entity_type"] == "review_candidate" for row in evidence_rows)


def test_reimport_protection_keeps_human_state_and_supersedes_changed_content(
    database,
) -> None:
    """Re-ingest is idempotent for unchanged content, supersedes a row whose
    SMILES changed under the same label, and leaves untouched rows alone."""
    same = [_candidate(smiles="*c1ccccc1", label="R1")]
    with database.mol_conn() as conn:
        persist_review_candidates("doc-1", same, conn=conn, recognition_version=1)
        # User reviews the row out-of-band
        conn.execute(
            "UPDATE markush_review_candidates "
            "SET review_status = 'confirmed', review_version = 2 "
            "WHERE doc_id = 'doc-1'"
        )
        conn.commit()

    with database.mol_conn() as conn:
        inserted = persist_review_candidates(
            "doc-1", same, conn=conn, recognition_version=1
        )
        assert inserted == 0, "same source + same content must be a no-op"
        row = conn.execute(
            "SELECT review_status, review_version FROM markush_review_candidates "
            "WHERE doc_id = 'doc-1'"
        ).fetchone()
    assert row["review_status"] == "confirmed"
    assert row["review_version"] == 2

    first = [_candidate(smiles="*c1ccccc1", label="R1")]
    second = [_candidate(smiles="*c1ccncc1", label="R1")]
    with database.mol_conn() as conn:
        persist_review_candidates("doc-2", first, conn=conn, recognition_version=1)
        # The pipeline writes ``DELETE FROM markush_*`` for the doc before
        # re-running, so the prior ``markush_fragments`` rows are gone,
        # but the review queue should NOT be wiped (it carries human
        # decisions).
        inserted = persist_review_candidates(
            "doc-2", second, conn=conn, recognition_version=1
        )
        assert inserted == 1
        rows = {
            r["smiles"]: r
            for r in conn.execute(
                "SELECT smiles, review_status, superseded_at "
                "FROM markush_review_candidates WHERE doc_id = 'doc-2'"
            )
        }
    assert len(rows) == 2
    old = rows["*c1ccccc1"]
    new = rows["*c1ccncc1"]
    assert old["review_status"] == "superseded"
    assert old["superseded_at"] is not None
    assert new["review_status"] == "pending"
    assert new["superseded_at"] is None

    relabel = [_candidate(smiles="*c1ccccc1", label="R2")]
    with database.mol_conn() as conn:
        persist_review_candidates("doc-3", first, conn=conn, recognition_version=1)
        inserted = persist_review_candidates(
            "doc-3", relabel, conn=conn, recognition_version=1
        )
        assert inserted == 1
        label_rows = conn.execute(
            "SELECT normalized_label, review_status FROM markush_review_candidates "
            "WHERE doc_id = 'doc-3'"
        ).fetchall()
    assert {row["normalized_label"] for row in label_rows} == {"R1", "R2"}
    assert all(row["review_status"] == "pending" for row in label_rows)

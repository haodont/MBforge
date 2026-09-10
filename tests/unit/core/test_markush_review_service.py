"""Unit tests for the Markush review service.

The service is the persistence-side counterpart of the pipeline's
``review_required`` branch. It owns:

- ``source_key`` / ``content_hash`` derivation
- Re-import protection: same source + same content keeps human state;
  same source + different content supersedes the old row and inserts a
  fresh ``pending`` row; new source creates a new ``pending`` row.
- Appending to ``markush_evidence`` and ``markush_decisions``.
"""

from __future__ import annotations

import json

import pytest

from mbforge.core.markush.provenance import (
    compute_content_hash,
    compute_source_key,
)
from mbforge.pipeline.detection.normalization import DetectionSource, NormalizedMolecule
from mbforge.storage.markush_candidates import persist_review_candidates
from mbforge.storage.sqlite.database import DatabaseManager


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
) -> NormalizedMolecule:
    molecule = NormalizedMolecule(
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


def test_compute_source_key_is_stable_across_bbox_jitter() -> None:
    """Bbox coordinates are quantized to 0.1 pt so OCR jitter doesn't
    produce a different source identity."""
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
    assert raw == jittered


def test_compute_source_key_changes_when_label_changes() -> None:
    a = compute_source_key("doc-1", 1, (10.0, 20.0, 110.0, 220.0), "R1")
    b = compute_source_key("doc-1", 1, (10.0, 20.0, 110.0, 220.0), "R2")
    assert a != b


def test_compute_content_hash_changes_when_smiles_change() -> None:
    a = compute_content_hash(
        canonical_smiles="*c1ccccc1",
        esmiles="*c1ccccc1",
        context="Formula I",
        recognition_version=1,
    )
    b = compute_content_hash(
        canonical_smiles="*c1ccncc1",
        esmiles="*c1ccncc1",
        context="Formula I",
        recognition_version=1,
    )
    assert a != b


def test_persist_review_candidates_inserts_pending_row(database) -> None:
    candidates = [_candidate(smiles="*c1ccccc1", label="R1")]
    with database.mol_conn() as conn:
        inserted = persist_review_candidates(
            doc_id="doc-1",
            candidates=candidates,
            conn=conn,
            recognition_version=1,
        )
    assert inserted == 1
    with database.mol_conn() as conn:
        row = conn.execute(
            "SELECT doc_id, predicted_role, normalized_label, label_kind, "
            "review_status, review_version, recognition_status "
            "FROM markush_review_candidates"
        ).fetchone()
    assert row["doc_id"] == "doc-1"
    assert row["predicted_role"] == "review_required"
    assert row["normalized_label"] == "R1"
    assert row["label_kind"] == "r_group"
    assert row["review_status"] == "pending"
    assert row["review_version"] == 1
    assert row["recognition_status"] == "valid"


def test_reimport_same_content_preserves_human_decision(database) -> None:
    """Re-ingesting the same SMILES + label must NOT reset a confirmed row."""
    candidates = [_candidate(smiles="*c1ccccc1", label="R1")]
    with database.mol_conn() as conn:
        persist_review_candidates("doc-1", candidates, conn=conn, recognition_version=1)
        # User reviews the row out-of-band
        conn.execute(
            "UPDATE markush_review_candidates "
            "SET review_status = 'confirmed', review_version = 2 "
            "WHERE source_key = (SELECT source_key FROM markush_review_candidates LIMIT 1)"
        )
        conn.commit()

    with database.mol_conn() as conn:
        inserted = persist_review_candidates(
            "doc-1", candidates, conn=conn, recognition_version=1
        )
    assert inserted == 0, "same source + same content must be a no-op"
    with database.mol_conn() as conn:
        row = conn.execute(
            "SELECT review_status, review_version FROM markush_review_candidates"
        ).fetchone()
    assert row["review_status"] == "confirmed"
    assert row["review_version"] == 2


def test_reimport_different_content_supersedes_old(database) -> None:
    """Same label, different SMILES → supersede old, insert new pending."""
    first = [_candidate(smiles="*c1ccccc1", label="R1")]
    second = [_candidate(smiles="*c1ccncc1", label="R1")]
    with database.mol_conn() as conn:
        persist_review_candidates("doc-1", first, conn=conn, recognition_version=1)
        # The pipeline writes ``DELETE FROM markush_*`` for the doc before
        # re-running, so the prior ``markush_fragments`` rows are gone,
        # but the review queue should NOT be wiped (it carries human
        # decisions).
        inserted = persist_review_candidates(
            "doc-1", second, conn=conn, recognition_version=1
        )
    assert inserted == 1
    with database.mol_conn() as conn:
        rows = conn.execute(
            "SELECT source_key, smiles, review_status, superseded_at "
            "FROM markush_review_candidates ORDER BY created_at"
        ).fetchall()
    assert len(rows) == 2
    # Old row: superseded
    old, new = rows
    assert old["smiles"] == "*c1ccccc1"
    assert old["review_status"] == "superseded"
    assert old["superseded_at"] is not None
    # New row: pending
    assert new["smiles"] == "*c1ccncc1"
    assert new["review_status"] == "pending"
    assert new["superseded_at"] is None


def test_reimport_new_label_creates_new_pending(database) -> None:
    """Different label → entirely new row, old one untouched."""
    first = [_candidate(smiles="*c1ccccc1", label="R1")]
    second = [_candidate(smiles="*c1ccccc1", label="R2")]
    with database.mol_conn() as conn:
        persist_review_candidates("doc-1", first, conn=conn, recognition_version=1)
        inserted = persist_review_candidates(
            "doc-1", second, conn=conn, recognition_version=1
        )
    assert inserted == 1
    with database.mol_conn() as conn:
        rows = conn.execute(
            "SELECT normalized_label, review_status "
            "FROM markush_review_candidates ORDER BY created_at"
        ).fetchall()
    assert {row["normalized_label"] for row in rows} == {"R1", "R2"}
    assert all(row["review_status"] == "pending" for row in rows)


def test_persist_writes_evidence_per_detection(database) -> None:
    """All detections of a candidate land in ``markush_evidence``."""
    molecule = NormalizedMolecule(
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


def test_persist_writes_decision_log(database) -> None:
    """A first-time insert writes a ``markush_decisions`` audit row."""
    candidates = [_candidate(smiles="*c1ccccc1", label="R1")]
    with database.mol_conn() as conn:
        persist_review_candidates("doc-1", candidates, conn=conn, recognition_version=1)
        decision = conn.execute(
            "SELECT action, new_state, snapshot FROM markush_decisions"
        ).fetchone()
    assert decision["action"] == "candidate_created"
    assert decision["new_state"] == "pending"
    snapshot = json.loads(decision["snapshot"])
    assert snapshot["normalized_label"] == "R1"
    assert snapshot["smiles"] == "*c1ccccc1"

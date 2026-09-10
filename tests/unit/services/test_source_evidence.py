"""Tests for the canonical source-evidence SQL query service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mbforge.core.evidence import SourceEvidence
from mbforge.pipeline.evidence_artifacts import DocumentEvidenceArtifact, PageFrame
from mbforge.pipeline.persist.source_evidence import persist_source_evidence
from mbforge.services.documents.source_evidence import (
    at,
    find_text,
    list_evidence,
    resolve,
    update_molecule,
)


def test_source_evidence_queries_resolve_text_and_bbox_intersection(
    tmp_path: Path,
) -> None:
    text = SourceEvidence.create(
        doc_id="doc-query",
        page=1,
        bbox=(10.0, 10.0, 20.0, 20.0),
        raw_text="IC50\n10 nM",
    )
    image = SourceEvidence.create(
        doc_id="doc-query",
        page=1,
        bbox=(30.0, 30.0, 40.0, 40.0),
        coref="storage/doc-query/crops/mol.png",
        kind="image_region",
    )
    other_page = SourceEvidence.create(
        doc_id="doc-query",
        page=2,
        bbox=(10.0, 10.0, 20.0, 20.0),
        raw_text="other",
    )
    persist_source_evidence(
        tmp_path,
        DocumentEvidenceArtifact(
            doc_id="doc-query",
            run_id="run-1",
            conventions={"origin": "bottom-left"},
            pages=[
                PageFrame(page=1, width=100.0, height=100.0),
                PageFrame(page=2, width=100.0, height=100.0),
            ],
            evidence=[text, image, other_page],
        ),
    )

    assert resolve(tmp_path, text.evidence_id) == text
    assert resolve(tmp_path, "missing") is None
    assert [item.evidence_id for item in list_evidence(tmp_path, "doc-query")] == [
        image.evidence_id,
        text.evidence_id,
        other_page.evidence_id,
    ]
    assert [
        item.evidence_id
        for item in list_evidence(tmp_path, "doc-query", page=1, kind="text_span")
    ] == [text.evidence_id]
    assert [
        item.evidence_id for item in at(tmp_path, "doc-query", 1, [15, 15, 35, 35])
    ] == [image.evidence_id, text.evidence_id]
    assert [
        item.evidence_id for item in find_text(tmp_path, "doc-query", "IC50  10 nM")
    ] == [text.evidence_id]


def test_source_evidence_at_requires_valid_bbox(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bbox"):
        at(tmp_path, "doc-query", 1, None)  # type: ignore[arg-type]


def test_source_evidence_persistence_is_idempotent_and_refreshable(
    tmp_path: Path,
) -> None:
    evidence = SourceEvidence.create(
        doc_id="doc-idempotent",
        page=1,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text="original",
    )
    artifact = DocumentEvidenceArtifact(
        doc_id="doc-idempotent",
        run_id="run-1",
        conventions={"origin": "bottom-left"},
        pages=[PageFrame(page=1, width=10.0, height=10.0)],
        evidence=[evidence],
    )

    assert persist_source_evidence(tmp_path, artifact) == 1
    assert persist_source_evidence(tmp_path, artifact) == 1

    # A re-detection of the same region keeps the geometry-keyed id but may
    # refresh the payload; the old row is deleted before the new one is
    # written, so exactly one row remains under that id.
    changed = SourceEvidence.create(
        doc_id="doc-idempotent",
        page=1,
        bbox=evidence.bbox,
        raw_text="changed",
    )
    assert changed.evidence_id == evidence.evidence_id
    assert (
        persist_source_evidence(
            tmp_path, artifact.model_copy(update={"evidence": [changed]})
        )
        == 1
    )

    refreshed = resolve(tmp_path, evidence.evidence_id)
    assert refreshed is not None
    assert refreshed.raw_text == "changed"
    assert list_evidence(tmp_path, "doc-idempotent") == [refreshed]


def test_source_evidence_batch_may_not_drop_existing_ids(tmp_path: Path) -> None:
    kept = SourceEvidence.create(
        doc_id="doc-drop",
        page=1,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text="kept",
    )
    dropped = SourceEvidence.create(
        doc_id="doc-drop",
        page=1,
        bbox=(5.0, 6.0, 7.0, 8.0),
        raw_text="dropped",
    )
    full = DocumentEvidenceArtifact(
        doc_id="doc-drop",
        run_id="run-1",
        conventions={"origin": "bottom-left"},
        pages=[PageFrame(page=1, width=10.0, height=10.0)],
        evidence=[kept, dropped],
    )
    assert persist_source_evidence(tmp_path, full) == 2

    with pytest.raises(ValueError, match="would drop 1 existing id"):
        persist_source_evidence(
            tmp_path,
            full.model_copy(update={"evidence": [kept]}),
        )


def test_update_molecule_overwrites_same_evidence_id_and_backs_up_source(
    tmp_path: Path,
) -> None:
    evidence = SourceEvidence.create(
        doc_id="doc-edit",
        page=1,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text=json.dumps(
            {"name": "1", "smiles": "CCO", "esmiles": "CCO", "moldet_conf": 0.95},
            ensure_ascii=False,
        ),
        coref="storage/doc-edit/crops/mol.png",
        kind="molecule",
    )
    persist_source_evidence(
        tmp_path,
        DocumentEvidenceArtifact(
            doc_id="doc-edit",
            run_id="run-1",
            conventions={"origin": "bottom-left"},
            pages=[PageFrame(page=1, width=10.0, height=10.0)],
            evidence=[evidence],
        ),
    )

    assert (
        update_molecule(tmp_path, "doc-edit", evidence.evidence_id, "1d", "CCN")
        == evidence.evidence_id
    )

    updated = resolve(tmp_path, evidence.evidence_id)
    assert updated is not None
    payload = json.loads(updated.raw_text)
    assert updated.evidence_id == evidence.evidence_id
    assert payload["name"] == "1d"
    assert payload["smiles"] == "CCN"
    assert payload["esmiles"] == "CCN"
    assert payload["moldet_conf"] == 1.0
    backups = list((tmp_path / ".mbforge" / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "library.db").is_file()


def test_update_molecule_allows_empty_name(tmp_path: Path) -> None:
    evidence = SourceEvidence.create(
        doc_id="doc-no-name",
        page=1,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text=json.dumps({"smiles": "CCO"}),
        kind="molecule",
    )
    persist_source_evidence(
        tmp_path,
        DocumentEvidenceArtifact(
            doc_id="doc-no-name",
            run_id="run-1",
            conventions={"origin": "bottom-left"},
            pages=[PageFrame(page=1, width=10.0, height=10.0)],
            evidence=[evidence],
        ),
    )

    assert (
        update_molecule(tmp_path, "doc-no-name", evidence.evidence_id, "", "CCN")
        == evidence.evidence_id
    )

    updated = resolve(tmp_path, evidence.evidence_id)
    assert updated is not None
    payload = json.loads(updated.raw_text)
    assert payload["name"] == ""
    assert payload["smiles"] == "CCN"

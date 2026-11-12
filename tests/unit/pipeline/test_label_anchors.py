# @tested-functions build_label_anchors, build_page_geometry, persist_label_anchors, anchor_coverage
"""ADR 0001 anchor index: production from evidence, persistence and coverage.

One usage test spans the producer, the store and the schema together: the
contract is that a printed designation becomes a stable, evidence-cited anchor
in the right key space, a phrase that merely mentions a compound does not, and
a re-extract reproduces the same index without duplicating it.
"""

from __future__ import annotations

import json
from pathlib import Path

from mbforge.db.sqlite.repositories import create_repositories
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.pipeline.artifacts.evidence_models import PageFrame
from mbforge.service.pipeline.extract.anchors import (
    build_label_anchors,
    build_page_geometry,
)

_DOC = "a" * 64


def _evidence() -> list[SourceEvidence]:
    return [
        SourceEvidence.create(
            doc_id=_DOC,
            page=1,
            bbox=(10, 700, 300, 720),
            raw_text="实施例17：目标化合物17的制备",
            kind="sec",
        ),
        SourceEvidence.create(
            doc_id=_DOC,
            page=1,
            bbox=(10, 600, 60, 615),
            raw_text="A-5",
            kind="text",
        ),
        # A phrase that mentions a compound names no drawing: not an anchor.
        SourceEvidence.create(
            doc_id=_DOC,
            page=1,
            bbox=(10, 500, 300, 520),
            raw_text="目标化合物11的制备过程如下",
            kind="text",
        ),
        SourceEvidence.create(
            doc_id=_DOC,
            page=2,
            bbox=(10, 700, 300, 720),
            raw_text="Example 2—Screening of Compounds",
            kind="sec",
        ),
        # A molecule observation is JSON, not printed text: never an anchor.
        SourceEvidence.create(
            doc_id=_DOC,
            page=2,
            bbox=(10, 400, 200, 500),
            raw_text=json.dumps({"smiles": "CCO", "name": "A-5"}),
            kind="molecule",
        ),
    ]


def test_anchor_index_production_persistence_and_coverage(tmp_path: Path) -> None:
    evidence = _evidence()
    anchors = build_label_anchors(evidence, doc_id=_DOC)

    by_key = {(a.anchor_kind, a.label_key): a for a in anchors}
    assert ("section_heading", "@example:17") in by_key
    assert ("section_heading", "@example:2") in by_key
    assert ("prose", "A-5") in by_key
    # The phrase and the molecule row produced no anchor.
    assert len(anchors) == 3
    assert all(a.anchor_kind in {"section_heading", "prose"} for a in anchors)
    # Each anchor cites the evidence row it was read from.
    assert (
        by_key[("section_heading", "@example:17")].evidence_id
        == evidence[0].evidence_id
    )
    assert by_key[("prose", "A-5")].evidence_id == evidence[1].evidence_id
    assert by_key[("prose", "A-5")].label_raw == "A-5"

    geometry = build_page_geometry(
        _DOC, [PageFrame(page=1, width=612, height=792, rotation=0)]
    )
    repositories = create_repositories(tmp_path)
    assert repositories.anchors.persist(_DOC, anchors, geometry) == 3

    coverage = repositories.anchors.coverage()
    assert coverage["anchors"] == 3
    assert coverage["documents"] == 1
    assert coverage["by_key_space"] == {"example": 2, "compound": 1}
    assert coverage["by_anchor_kind"] == {"section_heading": 2, "prose": 1}

    # A re-extract reproduces identical ids and does not duplicate the index.
    again = build_label_anchors(evidence, doc_id=_DOC)
    assert {a.anchor_id for a in again} == {a.anchor_id for a in anchors}
    repositories.anchors.persist(_DOC, again, geometry)
    assert repositories.anchors.coverage()["anchors"] == 3

    # Coverage scopes to one document.
    assert repositories.anchors.coverage(_DOC)["anchors"] == 3
    assert repositories.anchors.coverage("b" * 64)["anchors"] == 0

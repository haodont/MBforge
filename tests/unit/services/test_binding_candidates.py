"""Binding candidate package: readings joined to the structures that claim them.

Covers ``use_cases.documents.binding_candidates.binding_candidates`` — the read
surface that hands an agent the material to decide a designation → structure
binding. The contract is the join: a reading's designation reaches the
structures whose printed labels carry it, with the evidence to choose, and the
reading's current attribution travels with it. Nothing is written.
"""

from __future__ import annotations

import json
from pathlib import Path

from mbforge.contracts.measurement import (
    MeasurementAttribution,
    MeasurementRecord,
)
from mbforge.db.measurement_store import replace_document_measurements
from mbforge.db.source_evidence import persist_source_evidence
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.use_cases.documents.binding_candidates import binding_candidates

#: 1-D of CN119504738A: C13H19N5, monoisotopic 245.1641.
SMILES = "Cn1cc2c(N[C@H]3CC[C@@H](N)CC3)nccc2n1"


def _molecule(
    doc_id: str,
    page: int,
    bbox: tuple[float, float, float, float],
    smiles: str,
    label: str,
    source: str = "crop",
) -> SourceEvidence:
    """A molecule row whose drawing prints *label* beside it."""
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=bbox,
        kind="molecule",
        raw_text=json.dumps(
            {
                "smiles": smiles,
                "esmiles": smiles,
                "moldet_conf": 0.94,
                # The crop-label OCR read this designation off the drawing;
                # ``label_source`` records whether the page's own text or a
                # crop window supplied it.
                "name": label,
                "properties": {"label_source": source},
            },
            ensure_ascii=False,
        ),
    )


def _table(doc_id: str, page: int, text: str) -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=(10.0, 10.0, 20.0, 20.0),
        kind="tab",
        raw_text=text,
    )


def _reading(
    measurement_id: str,
    key: str,
    value: float,
    doc_id: str = "doc-bind",
    page: int = 2,
):
    return MeasurementRecord(
        measurement_id=measurement_id,
        doc_id=doc_id,
        metric="IC50",
        activity_type="IC50",
        original_value=value,
        original_unit="nM",
        canonical_value=value,
        canonical_unit="nM",
        operator="=",
        reference_raw=f"化合物{key}",
        reference_key=key,
        reference_type="compound",
        page_num=page,
        table_idx=0,
        row_idx=0,
        col_idx=1,
        evidence_ids=["ev-1"],
    )


def test_package_joins_a_reading_to_the_structures_that_claim_it(
    tmp_path: Path,
) -> None:
    """A designation reaches the structures whose printed labels carry it.

    The reading names ``化合物4``; the drawing prints ``化合物4`` and its name
    came off a crop window, so the candidate reports one source (``crop``) and
    one printing. ``化合物9`` is printed by the reading but no structure carries
    it, so it is an open decision with no candidates.
    """
    doc_id = "doc-bind"
    persist_source_evidence(
        tmp_path,
        [_molecule(doc_id, 5, (10.0, 10.0, 20.0, 20.0), SMILES, "化合物4")],
    )
    replace_document_measurements(
        tmp_path,
        doc_id,
        [_reading("m-4", "4", 12.0), _reading("m-9", "9", 80.0)],
        [
            MeasurementAttribution(
                attribution_id="a-1",
                measurement_id="m-4",
                mol_id=SMILES,
                doc_id=doc_id,
                method="rule",
                confidence=0.8,
                review_status="accepted",
            )
        ],
    )

    report = binding_candidates(tmp_path, doc_id)

    assert report["summary"]["readings"] == 2
    assert report["summary"]["attributed_readings"] == 1
    assert report["summary"]["unattributed_readings"] == 1
    assert report["summary"]["designations"] == 2
    assert report["summary"]["candidate_structures"] == 1

    by_key = {item["label_key"]: item for item in report["designations"]}
    bound = by_key["4"]
    assert bound["label_raw"] == "化合物4"
    assert bound["reading_ids"] == ["m-4"]
    assert bound["pages"] == [2, 5]
    assert bound["context_types"] == ["reading", "structure_label"]
    assert bound["attribution"]["mol_id"] == SMILES
    assert bound["attribution"]["method"] == "rule"
    assert bound["has_reading"] is True
    assert len(bound["candidates"]) == 1
    candidate = bound["candidates"][0]
    assert candidate["label_keys"] == ["4"]
    assert candidate["label_sources"] == ["crop"]
    assert candidate["designation_counts"] == {"4": 1}
    assert candidate["owns"] is True
    assert candidate["formula"] == "C13H19N5"
    assert candidate["page"] == 5

    open_gap = by_key["9"]
    assert open_gap["candidates"] == []
    assert open_gap["attribution"] is None
    assert open_gap["reading_ids"] == ["m-9"]
    assert open_gap["has_reading"] is True


def test_package_pages_designations_and_reports_table_tokens(
    tmp_path: Path,
) -> None:
    """The designation page is bounded, and a table's molecule tokens are reported.

    ``offset``/``limit`` page the designations while ``total`` keeps the real
    count, so a caller can page without under-claiming completeness. A table
    cell that kept its ``[MOL:n]`` placeholder is reported with its page and
    evidence row, and no structure is invented for it.
    """
    doc_id = "doc-bind-page"
    persist_source_evidence(
        tmp_path,
        [
            _molecule(doc_id, 5, (10.0, 10.0, 20.0, 20.0), SMILES, "化合物1"),
            _molecule(doc_id, 6, (30.0, 30.0, 40.0, 40.0), SMILES, "化合物2"),
            _molecule(doc_id, 7, (50.0, 50.0, 60.0, 60.0), SMILES, "化合物3"),
            _table(doc_id, 8, "| 实施例 | 结构 | --- | --- | | 实施例1 | [MOL:0] |"),
        ],
    )
    replace_document_measurements(
        tmp_path,
        doc_id,
        [
            _reading("m-1", "1", 1.0, doc_id),
            _reading("m-2", "2", 2.0, doc_id),
            _reading("m-3", "3", 3.0, doc_id),
        ],
    )

    first = binding_candidates(tmp_path, doc_id, offset=0, limit=2)
    assert first["total"] == 3
    assert [item["label_key"] for item in first["designations"]] == ["1", "2"]
    assert first["summary"]["readings"] == 3
    assert first["summary"]["table_cells"] == 1

    second = binding_candidates(tmp_path, doc_id, offset=2, limit=2)
    assert [item["label_key"] for item in second["designations"]] == ["3"]

    cells = first["table_cells"]
    assert len(cells) == 1
    assert cells[0]["page"] == 8
    assert cells[0]["tokens"] == ["[MOL:0]"]
    assert cells[0]["evidence_id"]

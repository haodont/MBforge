"""Activity reading endpoints.

A reading is listed whether or not a structure owns it: the document printed it,
so it is citable data. ``attributed`` reports whether a structure link exists.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.contracts.measurement import (
    MeasurementAttribution,
    MeasurementRecord,
)
from mbforge.db.measurement_store import replace_document_measurements
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.activity_queries import (
    dataset_stats,
    list_activity_records,
    list_measurements,
)


def _seed(tmp_library: Path) -> None:
    """One attached reading and one that no structure owns."""
    db = DatabaseManager.get(str(tmp_library))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO molecules (
                mol_id, smiles, esmiles, name, source_doc,
                source_type, status, canonical_smiles
            ) VALUES ('CCO', 'CCO', 'CCO', 'compound-1', 'doc-1',
                      'image', 'pending', 'CCO')
            """
        )
    replace_document_measurements(
        tmp_library,
        "doc-1",
        [
            MeasurementRecord(
                measurement_id="meas-attached",
                doc_id="doc-1",
                entry_id="1",
                metric="IC50",
                activity_type="IC50",
                original_value=12.0,
                original_unit="nM",
                canonical_value=12.0,
                canonical_unit="nM",
                operator="=",
                target="EGFR",
                assay_type="binding",
                assay_description="EGFR binding",
                raw_text="IC50 EGFR = 12 nM",
                page_num=2,
                table_idx=0,
                row_idx=1,
                col_idx=2,
                row_label="compound-1",
                evidence_ids=["ev-1"],
            ),
            MeasurementRecord(
                measurement_id="meas-orphan",
                doc_id="doc-1",
                entry_id="2",
                metric="IC50",
                activity_type="IC50",
                original_value=80.0,
                original_unit="nM",
                canonical_value=80.0,
                canonical_unit="nM",
                operator="=",
                target="EGFR",
                assay_type="binding",
                assay_description="EGFR binding",
                raw_text="IC50 EGFR = 80 nM",
                page_num=3,
                table_idx=0,
                row_idx=2,
                col_idx=2,
                row_label="compound-2",
                evidence_ids=["ev-2"],
            ),
        ],
        [
            MeasurementAttribution(
                attribution_id="attr-1",
                measurement_id="meas-attached",
                mol_id="CCO",
                doc_id="doc-1",
                method="rule",
                evidence_id="ev-1",
            )
        ],
    )
    get_repositories(str(tmp_library)).review.insert_review_item(
        item_id="review-activity-1",
        kind="activity_match",
        doc_id="doc-1",
        page=3,
        name="compound-2",
        confidence=0.35,
        reasons=["orphan_activity"],
        context_text="IC50 EGFR = 80 nM",
        payload={
            "activity_type": "IC50",
            "value": 80.0,
            "value_original": 80.0,
            "unit_original": "nM",
            "unit_canonical": "nM",
            "target": "EGFR",
            "assay_type": "binding",
            "mol_id": None,
        },
    )


def test_readings_without_a_structure_are_stored_and_listed(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A reading no structure owns is data, not a rejected row."""
    _seed(tmp_library)

    response = app_client.get(
        "/api/v1/activities/documents/doc-1",
        params={"library_root": str(tmp_library)},
    )

    assert response.status_code == 200, response.text
    records = response.json()
    assert [record["activity_id"] for record in records] == [
        "meas-attached",
        "meas-orphan",
        None,
    ]
    assert records[2]["review_id"] == "review-activity-1"
    assert [record["source"] for record in records] == [
        "measurements",
        "measurements",
        "review_items",
    ]
    attached, orphan = records[0], records[1]
    assert attached["attributed"] is True
    assert attached["mol_ids"] == ["CCO"]
    assert attached["evidence_grade"] == "measured"
    assert attached["raw_text"] == "IC50 EGFR = 12 nM"
    # The whole point: no structure, still a citable, listed reading.
    assert orphan["attributed"] is False
    assert orphan["mol_ids"] == []
    assert orphan["value"] == 80.0
    assert orphan["unit_original"] == "nM"
    assert records[2]["status"] == "pending"
    assert records[2]["page_num"] == 3

    filtered = app_client.get(
        "/api/v1/activities/documents/doc-1",
        params={
            "library_root": str(tmp_library),
            "target": "not-present",
            "limit": 1,
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json() == []


def test_dataset_stats_separate_attributed_from_total(
    tmp_library: Path,
) -> None:
    """Coverage counts expose the extraction backlog instead of hiding it."""
    _seed(tmp_library)

    stats = dataset_stats(str(tmp_library), "doc-1")

    assert stats.total == 2
    assert stats.attributed == 1
    assert stats.unattributed == 1
    assert stats.by_target["EGFR"] == 2


def test_measurement_filters_select_by_target_and_grade(tmp_library: Path) -> None:
    _seed(tmp_library)

    by_target = list_measurements(str(tmp_library), doc_id="doc-1", target="egfr")
    assert [row["measurement_id"] for row in by_target] == [
        "meas-attached",
        "meas-orphan",
    ]

    predicted = list_measurements(
        str(tmp_library), doc_id="doc-1", evidence_grade="predicted"
    )
    assert predicted == []

    by_metric = list_measurements(str(tmp_library), doc_id="doc-1", metric="ic50")
    assert len(by_metric) == 2

    records = list_activity_records(str(tmp_library), "doc-1", limit=10)
    # The seeded review candidate is listed too; it is pending, not a fact.
    assert [record["activity_id"] for record in records] == [
        "meas-attached",
        "meas-orphan",
        None,
    ]
    assert [record["source"] for record in records] == [
        "measurements",
        "measurements",
        "review_items",
    ]


def test_attribution_gap_is_split_by_whether_the_structure_exists(
    tmp_library: Path,
) -> None:
    """A gap the source causes and a gap we cause are reported separately.

    ``77-A`` is printed with only SFC/LC-MS data — the document never drew it, so
    no index can bind it. A designation that *was* drawn but stayed unmatched is
    a defect. Reporting one "unattributed" number hides that difference.
    """
    db = DatabaseManager.get(str(tmp_library))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO molecules (mol_id, smiles, name, source_doc,
                                   source_type, status, canonical_smiles, labels)
            VALUES ('drawn-47', 'CCO', '47', 'doc-1', 'image', 'active', 'CCO', '[]')
            """
        )
        conn.execute(
            """
            INSERT INTO molecule_detections (mol_id, doc_id, page,
                                             bbox_x0, bbox_y0, bbox_x1, bbox_y1)
            VALUES ('drawn-47', 'doc-1', 5, 0.0, 0.0, 1.0, 1.0)
            """
        )
    replace_document_measurements(
        tmp_library,
        "doc-1",
        [
            # The document drew 47 but no rule bound this reading to it.
            MeasurementRecord(
                measurement_id="m-drawn",
                doc_id="doc-1",
                entry_id="entry-47",
                reference_key="47",
                metric="IC50",
                activity_type="IC50",
                original_value=1.0,
                original_unit="nM",
            ),
            # 77-A is printed, but the document never drew its structure.
            MeasurementRecord(
                measurement_id="m-undrawn",
                doc_id="doc-1",
                entry_id="entry-77a",
                reference_key="77-A",
                metric="IC50",
                activity_type="IC50",
                original_value=2.0,
                original_unit="nM",
            ),
            # No designation at all.
            MeasurementRecord(
                measurement_id="m-bare",
                doc_id="doc-1",
                metric="IC50",
                activity_type="IC50",
                original_value=3.0,
                original_unit="nM",
            ),
        ],
    )

    stats = dataset_stats(str(tmp_library), "doc-1")

    assert stats.total == 3
    assert stats.attributed == 0
    assert stats.unattributed_by_reason == {
        "structure_detected_unmatched": 1,
        "designation_without_structure": 1,
        "no_printed_designation": 1,
    }

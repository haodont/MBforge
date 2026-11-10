"""Activity reading endpoints.

A reading is listed whether or not a structure owns it: the document printed it,
so it is citable data. ``attributed`` reports whether a structure link exists.
Functions under test: activity HTTP routes and ``export_structure_activity``.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from mbforge.contracts.measurement import (
    MeasurementAttribution,
    MeasurementRecord,
)
from mbforge.db.measurement_store import replace_document_measurements
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.patent_analysis import evidence_signature
from mbforge.service.pipeline.artifacts.hydration import load_detections
from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.activity_queries import (
    dataset_stats,
    list_activity_records,
    list_measurements,
)
from mbforge.service.use_cases.documents.patent_facts import publish_document_facts


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
    ]
    assert [record["source"] for record in records] == [
        "measurements",
        "measurements",
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
    assert [record["activity_id"] for record in records] == [
        "meas-attached",
        "meas-orphan",
    ]
    assert [record["source"] for record in records] == [
        "measurements",
        "measurements",
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


def test_readings_filter_by_value_and_say_why_they_have_no_structure(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A dataset question filters by metric/value; each row explains its gap."""

    replace_document_measurements(
        tmp_library,
        "doc-1",
        [
            MeasurementRecord(
                measurement_id="m-low",
                doc_id="doc-1",
                entry_id="entry-4",
                reference_key="4",
                metric="IC50",
                activity_type="IC50",
                original_value=12.0,
                original_unit="nM",
                canonical_value=12.0,
                canonical_unit="nM",
            ),
            MeasurementRecord(
                measurement_id="m-high",
                doc_id="doc-1",
                entry_id="entry-9",
                reference_key="9",
                metric="IC50",
                activity_type="IC50",
                original_value=120.0,
                original_unit="nM",
                canonical_value=120.0,
                canonical_unit="nM",
            ),
        ],
    )

    filtered = app_client.get(
        "/api/v1/activities/documents/doc-1",
        params={
            "library_root": str(tmp_library),
            "metric": "IC50",
            "max_value": 40,
        },
    )

    assert filtered.status_code == 200
    rows = filtered.json()
    assert [row["value"] for row in rows] == [12.0]
    # Nothing is bound, and the document drew nothing: that is a source fact.
    assert rows[0]["reasons"] == ["document_has_no_detections"]
    stats = app_client.get(
        "/api/v1/activities/documents/doc-1/stats",
        params={"library_root": str(tmp_library)},
    )
    assert stats.status_code == 200
    assert stats.json()["total"] == 2


def test_an_unread_label_is_reported_as_recoverable_not_as_undrawn(
    tmp_library: Path,
) -> None:
    """A drawn-but-unread designation is backlog, not a source fact.

    ``document_label_numbers`` only knows the designations the pipeline read; when
    the document drew structures whose number was never read, calling the missing
    designation "never drawn" understates the extraction gap.
    """
    replace_document_measurements(
        tmp_library,
        "doc-1",
        [
            MeasurementRecord(
                measurement_id="m-undrawn",
                doc_id="doc-1",
                entry_id="entry-77a",
                reference_key="77-A",
                metric="IC50",
                activity_type="IC50",
                original_value=2.0,
                original_unit="nM",
            )
        ],
    )
    db = DatabaseManager.get(str(tmp_library))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, canonical_smiles, name, source_doc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mol-unlabeled", "CCO", "CCO", "", "doc-1"),
        )
        conn.execute(
            "INSERT INTO molecule_detections (mol_id, doc_id, page) VALUES (?, ?, ?)",
            ("mol-unlabeled", "doc-1", 1),
        )
        conn.commit()

    stats = dataset_stats(str(tmp_library), "doc-1")

    assert stats.unattributed_by_reason == {"label_not_read": 1}


def test_export_preserves_readings_stereochemistry_and_citations_and_refuses_stale_sources(
    app_client: TestClient,
    tmp_library: Path,
) -> None:
    """A downloadable dataset never hides missing links or presents conflicts as pairs."""
    repos = get_repositories(tmp_library)
    repos.documents.insert(
        {"doc_id": "doc-export", "file_name": "export.pdf", "created_at": "2026-10-30"}
    )
    evidence = [
        SourceEvidence(
            "doc-export",
            1,
            (0, 0, 30, 30),
            kind="molecule",
            raw_text=json.dumps({"smiles": "C[C@H](O)F", "esmiles": "C[C@H](O)F"}),
        ),
        SourceEvidence(
            "doc-export",
            1,
            (40, 0, 70, 30),
            kind="molecule",
            raw_text=json.dumps({"smiles": "C[C@@H](O)F", "esmiles": "C[C@@H](O)F"}),
        ),
        SourceEvidence(
            "doc-export",
            2,
            (0, 0, 100, 100),
            kind="tab",
            raw_text="1 IC50 1.5 μM; pIC50 >7; activity +++; 2 IC50 12 nM",
        ),
        SourceEvidence("doc-export", 1, (0, 40, 100, 80), raw_text="Compound 1"),
        SourceEvidence(
            "doc-export",
            2,
            (0, 110, 100, 150),
            raw_text="Human MRGPRX2 calcium assay, HEK293",
        ),
    ]
    repos.evidence.persist(evidence)
    structure_id, _, reading_id, entry_id, assay_id = [e.evidence_id for e in evidence]

    def reading(mid: str, **updates: object) -> dict:
        return {
            "measurement_id": mid,
            "doc_id": "doc-export",
            "compound_entry_id": "entry-1",
            "assay_method_id": "assay-1",
            "metric": "IC50",
            "page_num": 2,
            "value": {
                "original_value": 1.5,
                "original_unit": "μM",
                "raw_text": "1.5",
                "operator": "=",
            },
            "evidence_ids": [reading_id],
            **updates,
        }

    artifact = PatentFactsArtifact(
        doc_id="doc-export",
        run_id="run-export",
        entries=[
            {
                "entry_id": "entry-1",
                "label_raw": "Compound 1",
                "entity_id": "C[C@H](O)F",
                "evidence_ids": [entry_id],
            }
        ],
        assay_methods=[
            {
                "assay_method_id": "assay-1",
                "target": "MRGPRX2",
                "system": "human",
                "conditions": {"cell_line": "HEK293"},
                "evidence_ids": [assay_id],
            }
        ],
        measurements=[
            reading("m-linear"),
            reading(
                "m-log",
                metric="pIC50",
                value={
                    "original_value": 7.0,
                    "original_unit": "",
                    "raw_text": ">7",
                    "operator": "<",
                    "canonical_value": 100.0,
                },
            ),
            reading(
                "m-bin",
                value={
                    "raw_text": "+++",
                    "qualitative_value": "+++",
                    "qualitative_rank": 3,
                    "qualitative_scheme": "plus",
                },
                measurement_kind="qualitative",
            ),
            reading("m-orphan", compound_entry_id=None),
            reading("m-conflict", mol_id="C[C@@H](O)F"),
            reading("m-uncitable", evidence_ids=["missing-evidence"]),
        ],
        review_candidates=[
            {"reason": "llm_only", "source_quote": "unverified proposal"}
        ],
    )
    publish_document_facts(
        tmp_library,
        doc_id="doc-export",
        artifact=artifact,
        evidence_signature=evidence_signature(
            (e.evidence_id, e.page, e.kind, e.raw_text) for e in evidence
        ),
        candidates=load_detections(tmp_library, "doc-export")[0],
    )
    assert repos.measurements.attributions_for(["m-conflict"]) == {}
    response = app_client.post(
        "/api/v1/activities/export",
        json={
            "doc_ids": ["doc-export", "doc-export"],
            "library_root": str(tmp_library),
        },
    )
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    with ZipFile(io.BytesIO(response.content)) as archive:
        matched = list(
            csv.DictReader(
                io.StringIO(archive.read("structure_activity.csv").decode("utf-8-sig"))
            )
        )
        unresolved = list(
            csv.DictReader(
                io.StringIO(archive.read("unresolved.csv").decode("utf-8-sig"))
            )
        )
        dataset = json.loads(archive.read("dataset.json"))
    assert len(matched) == len(unresolved) == 3
    linear, log, bin_row = matched
    assert linear["canonical_smiles"] == "C[C@H](O)F"
    assert linear["mol_id"]
    assert (
        linear["original_value"],
        linear["original_unit"],
        linear["canonical_value"],
        linear["canonical_unit"],
    ) == ("1.5", "μM", "1500.0", "nM")
    assert (
        log["operator_original"],
        log["operator"],
        log["canonical_metric"],
        log["canonical_value"],
    ) == (">", "<", "IC50", "100.0")
    assert bin_row["qualitative_raw"] == "'+++" and bin_row["canonical_value"] == ""
    assert all(row["review_status"] == "pending" for row in matched)
    assert [json.loads(row["reasons"]) for row in unresolved] == [
        ["structure_not_resolved", "missing_structure_evidence"],
        ["conflicting_structure_references", "missing_structure_evidence"],
        ["invalid_reading_evidence", "reading_page_mismatch"],
    ]
    doc = dataset["documents"][0]
    assert len(doc["rows"]) == 6 and doc["revision"] == 1
    assert doc["rows"][2]["qualitative_raw"] == "+++"
    assert doc["facts"]["review_candidates"] == artifact.review_candidates
    cited = {e["evidence_id"]: e for e in doc["evidence"]}
    assert cited[structure_id]["page"] == 1 and cited[structure_id]["bbox"] == [
        0,
        0,
        30,
        30,
    ]
    assert cited[reading_id]["raw_text"] == evidence[2].raw_text
    saved = repos.molecules.find_row("C[C@H](O)F")
    repos.molecules.update(
        saved["mol_id"],
        {"smiles": "CCO", "canonical_smiles": "CCO", "review_status": "confirmed"},
    )
    corrected = app_client.post(
        "/api/v1/activities/export",
        json={"doc_ids": ["doc-export"], "library_root": str(tmp_library)},
    )
    assert corrected.status_code == 200
    with ZipFile(io.BytesIO(corrected.content)) as archive:
        corrected_row = json.loads(archive.read("dataset.json"))["documents"][0][
            "rows"
        ][0]
    assert "structure_identity_changed" in corrected_row["reasons"]
    assert corrected_row["canonical_smiles"] is None
    assert corrected_row["recognized_smiles"] == "C[C@H](O)F"
    assert corrected_row["current_canonical_smiles"] == "CCO"
    repos.molecules.bulk_update_status([saved["mol_id"]], "rejected")
    rejected = app_client.post(
        "/api/v1/activities/export",
        json={"doc_ids": ["doc-export"], "library_root": str(tmp_library)},
    )
    assert rejected.status_code == 200
    with ZipFile(io.BytesIO(rejected.content)) as archive:
        rejected_dataset = json.loads(archive.read("dataset.json"))
    assert rejected_dataset["counts"] == {"matched_pending_review": 0, "unresolved": 6}
    assert (
        "structure_rejected" in rejected_dataset["documents"][0]["rows"][0]["reasons"]
    )
    # Changing the canonical source invalidates the export instead of trusting a stale projection.
    repos.evidence.persist(
        [
            *evidence[:2],
            SourceEvidence(
                "doc-export", 2, (0, 0, 100, 100), kind="tab", raw_text="changed"
            ),
            *evidence[3:],
        ]
    )
    stale = app_client.post(
        "/api/v1/activities/export",
        json={"doc_ids": ["doc-export"], "library_root": str(tmp_library)},
    )
    assert stale.status_code == 409

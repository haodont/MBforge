from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.services.documents.activity_queries import (
    list_activities,
    list_activity_records,
)
from mbforge.services.review_queue import insert_review_item
from mbforge.storage.sqlite.database import DatabaseManager


def _seed_activity_data(library_root: Path) -> None:
    db = DatabaseManager.get(str(library_root))
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
        conn.execute(
            """
            INSERT INTO activities (
                activity_id, mol_id, doc_id, activity_type, value,
                value_original, unit_original, operator, measurement_kind,
                metric, value_canonical, unit_canonical, operator_original,
                scale, value_text, target, assay_type, assay_description,
                confidence, page_num, table_idx, row_idx, col_idx, row_label,
                row_smiles, raw_text
            ) VALUES (
                'activity-1', 'CCO', 'doc-1', 'IC50', 12.0, 12.0, 'nM',
                '=', 'quantitative', 'IC50', 12.0, 'nM', '=', 'linear',
                '12 nM', 'EGFR', 'binding', 'EGFR binding', 0.95, 2, 0, 1,
                2, 'compound-1', 'CCO', 'IC50 EGFR = 12 nM'
            )
            """
        )
        insert_review_item(
            conn,
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


def test_activity_document_endpoint_returns_persisted_and_review_records(
    app_client: TestClient, tmp_library: Path
) -> None:
    _seed_activity_data(tmp_library)

    response = app_client.get(
        "/api/v1/activities/documents/doc-1",
        params={"library_root": str(tmp_library)},
    )

    assert response.status_code == 200, response.text
    records = response.json()
    assert [record["source"] for record in records] == [
        "activities",
        "review_items",
    ]
    assert records[0]["activity_id"] == "activity-1"
    assert records[0]["status"] == "persisted"
    assert records[0]["raw_text"] == "IC50 EGFR = 12 nM"
    assert records[1]["review_id"] == "review-activity-1"
    assert records[1]["status"] == "pending"
    assert records[1]["value"] == 80.0
    assert records[1]["page_num"] == 3

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


def test_list_activities_projects_rows_from_legacy_schema_without_optional_columns(
    app_client: TestClient, tmp_library: Path
) -> None:
    library_root = tmp_library
    db_path = library_root / ".mbforge" / "library.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE activities (
                activity_id TEXT PRIMARY KEY,
                mol_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                value REAL,
                target TEXT,
                assay_description TEXT,
                confidence REAL,
                table_idx INTEGER,
                row_idx INTEGER,
                row_label TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO activities (
                activity_id, mol_id, doc_id, activity_type, value, target,
                assay_description, confidence, table_idx, row_idx, row_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "activity-legacy-late",
                    "mol-legacy-late",
                    "legacy-doc",
                    "IC50",
                    20.0,
                    "EGFR",
                    "binding",
                    0.8,
                    2,
                    0,
                    "compound-late",
                ),
                (
                    "activity-legacy-early",
                    "mol-legacy-early",
                    "legacy-doc",
                    "IC50",
                    10.0,
                    "EGFR",
                    "binding",
                    0.9,
                    1,
                    3,
                    "compound-early",
                ),
            ],
        )

    DatabaseManager.get(str(library_root)).initialize()

    records = list_activities(
        str(library_root),
        "legacy-doc",
        target="egfr",
        assay_description="BINDING",
    )

    assert [
        (
            record["activity_id"],
            record["value"],
            record["target"],
            record["assay_description"],
            record["table_idx"],
            record["row_idx"],
        )
        for record in records
    ] == [
        ("activity-legacy-early", 10.0, "EGFR", "binding", 1, 3),
        ("activity-legacy-late", 20.0, "EGFR", "binding", 2, 0),
    ]
    missing_columns = (
        "value_original",
        "unit_original",
        "operator",
        "metric",
        "page_num",
        "col_idx",
        "row_smiles",
        "raw_text",
        "created_at",
    )
    assert all(
        record[column] is None for record in records for column in missing_columns
    )
    assert list_activities(str(library_root), "legacy-doc", target="not-present") == []
    assert (
        list_activities(str(library_root), "legacy-doc", assay_description="cellular")
        == []
    )

    projected_records = list_activity_records(
        str(library_root),
        "legacy-doc",
        target="EGFR",
        assay_description="binding",
    )
    assert [record["activity_id"] for record in projected_records] == [
        "activity-legacy-early",
        "activity-legacy-late",
    ]

    response = app_client.get(
        "/api/v1/activities/documents/legacy-doc",
        params={
            "library_root": str(library_root),
            "target": "EGFR",
            "assay_description": "binding",
        },
    )

    assert response.status_code == 200, response.text
    api_records = response.json()
    assert [record["activity_id"] for record in api_records] == [
        "activity-legacy-early",
        "activity-legacy-late",
    ]
    assert api_records[0]["value_original"] is None
    assert api_records[0]["page_num"] is None

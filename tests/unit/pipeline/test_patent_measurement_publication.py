"""Patent readings reach SQL without a structure, and none are collapsed.

Functions under test: ``publish_document_facts``, ``measurement_records``,
and ``measurement_attributions``.

The regression this file guards: the publication path used to keep only readings
that resolved to a structure and then only the **first** reading per molecule, so
a document's other assays, targets and doses never reached the database.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.contracts.measurement import MeasurementQuery
from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.service.pipeline.patent.measurement_records import (
    measurement_attributions,
    measurement_records,
)
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.patent_facts import publish_document_facts


def _measurement(
    measurement_id: str,
    *,
    entry_id: str | None,
    metric: str,
    value: float,
    unit: str = "nM",
    target: str = "EGFR",
    page: int = 2,
    row_idx: int = 1,
) -> dict:
    return {
        "measurement_id": measurement_id,
        "doc_id": "doc-1",
        "compound_entry_id": entry_id,
        "assay_method_id": "assay-1",
        "mol_id": None,
        "metric": metric,
        "linking_status": "linked",
        "value": {
            "raw_text": str(value),
            "operator": "=",
            "original_value": value,
            "original_unit": unit,
            "canonical_value": value,
            "canonical_unit": unit,
            "qualitative_value": "",
            "qualitative_rank": None,
            "qualitative_scheme": "",
            "qualitative_label": "",
        },
        "evidence_ids": [f"ev-{measurement_id}"],
        "provenance": {
            "reference_raw": entry_id or "",
            "reference_key": entry_id or "",
            "reference_type": "compound",
            "column_target": target,
        },
        "page_num": page,
        "table_idx": 0,
        "row_idx": row_idx,
        "col_idx": 1,
    }


def test_two_readings_of_one_structure_are_both_stored(tmp_library: Path) -> None:
    """One structure with two assays keeps both readings, not just the first."""
    artifact = PatentFactsArtifact(
        doc_id="doc-1",
        run_id="run-1",
        entries=[
            {
                "entry_id": "entry-1",
                "doc_id": "doc-1",
                "label_key": "1",
                "entity_id": "CCO",
            }
        ],
        assay_methods=[
            {
                "assay_method_id": "assay-1",
                "doc_id": "doc-1",
                "target": "EGFR",
                "system": "human",
                "assay_type": "binding",
            }
        ],
        measurements=[
            _measurement("m-ic50", entry_id="entry-1", metric="IC50", value=12.0),
            _measurement(
                "m-ki",
                entry_id="entry-1",
                metric="Ki",
                value=3.5,
                target="MRGPRX1",
                row_idx=2,
            ),
        ],
    )

    publish_document_facts(
        tmp_library,
        doc_id="doc-1",
        artifact=artifact,
        evidence_signature="sig-1",
        candidates=(),
    )

    rows = get_repositories(str(tmp_library)).measurements.list(
        MeasurementQuery(doc_id="doc-1")
    )

    assert [row["measurement_id"] for row in rows] == ["m-ic50", "m-ki"]
    assert [row["metric"] for row in rows] == ["IC50", "Ki"]
    assert [row["original_value"] for row in rows] == [12.0, 3.5]
    # A selectivity column's explicit target overrides the shared assay target.
    assert [row["target"] for row in rows] == ["EGFR", "MRGPRX1"]
    assert {row["species"] for row in rows} == {"human"}


def test_reading_without_a_structure_is_stored_without_attribution(
    tmp_library: Path,
) -> None:
    """The common case: a printed reading no structure owns is still stored."""
    artifact = PatentFactsArtifact(
        doc_id="doc-1",
        run_id="run-1",
        entries=[{"entry_id": "entry-1", "doc_id": "doc-1", "label_key": "1"}],
        measurements=[
            _measurement("m-orphan", entry_id="entry-1", metric="IC50", value=60.7),
            _measurement("m-bare", entry_id=None, metric="IC50", value=8.0, row_idx=2),
        ],
    )

    publish_document_facts(
        tmp_library,
        doc_id="doc-1",
        artifact=artifact,
        evidence_signature="sig-1",
        candidates=(),
    )

    repositories = get_repositories(str(tmp_library))
    rows = repositories.measurements.list(MeasurementQuery(doc_id="doc-1"))
    assert [row["measurement_id"] for row in rows] == ["m-orphan", "m-bare"]
    assert repositories.measurements.attributions_for(["m-orphan", "m-bare"]) == {}

    stats = repositories.measurements.stats("doc-1")
    assert stats.total == 2
    assert stats.attributed == 0


def test_republishing_replaces_readings_instead_of_duplicating(
    tmp_library: Path,
) -> None:
    """A re-run rewrites the document's readings; it never accumulates them."""
    artifact = PatentFactsArtifact(
        doc_id="doc-1",
        run_id="run-1",
        measurements=[_measurement("m-1", entry_id=None, metric="IC50", value=5.0)],
    )
    publish_document_facts(
        tmp_library,
        doc_id="doc-1",
        artifact=artifact,
        evidence_signature="sig-1",
    )
    publish_document_facts(
        tmp_library,
        doc_id="doc-1",
        artifact=artifact,
        evidence_signature="sig-1",
    )

    rows = get_repositories(str(tmp_library)).measurements.list(
        MeasurementQuery(doc_id="doc-1")
    )
    assert [row["measurement_id"] for row in rows] == ["m-1"]


def test_attribution_resolves_through_the_cited_entry(tmp_library: Path) -> None:
    """A reading whose entry carries a structure attributes to that structure."""
    artifact = PatentFactsArtifact(
        doc_id="doc-1",
        run_id="run-1",
        entries=[
            {
                "entry_id": "entry-1",
                "doc_id": "doc-1",
                "label_key": "1",
                "entity_id": "CCO",
            }
        ],
        measurements=[
            _measurement("m-1", entry_id="entry-1", metric="IC50", value=12.0)
        ],
    )

    publish_document_facts(
        tmp_library,
        doc_id="doc-1",
        artifact=artifact,
        evidence_signature="sig-1",
    )

    repositories = get_repositories(str(tmp_library))
    links = repositories.measurements.attributions_for(["m-1"])
    assert [link["mol_id"] for link in links["m-1"]] == ["CCO"]

    stats = repositories.measurements.stats("doc-1")
    assert (stats.total, stats.attributed) == (1, 1)


def test_records_keep_every_reading_and_attributions_only_the_resolved() -> None:
    """Pure projection: no filtering by structure, links only where resolved."""
    measurements = [
        _measurement("m-1", entry_id="entry-1", metric="IC50", value=12.0),
        _measurement("m-2", entry_id="entry-2", metric="Ki", value=4.0, row_idx=2),
    ]
    entries = [
        {"entry_id": "entry-1", "entity_id": "CCO"},
        {"entry_id": "entry-2", "entity_id": None},
    ]

    records = measurement_records(
        doc_id="doc-1", run_id="run-1", measurements=measurements
    )
    attributions = measurement_attributions(
        doc_id="doc-1",
        records=records,
        measurements=measurements,
        entries=entries,
    )

    assert len(records) == 2
    assert [item.measurement_id for item in attributions] == ["m-1"]
    assert attributions[0].mol_id == "CCO"
    assert all(record.evidence_grade == "measured" for record in records)

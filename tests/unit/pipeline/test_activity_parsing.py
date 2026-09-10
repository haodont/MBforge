"""Unit tests for ``mbforge.pipeline.activity.parsing.tables``.

Targets the deterministic table-parsing primitives that used to live
inside ``mbforge.pipeline.activity.extraction``. The existing pipeline
tests already cover them transitively through the orchestrator; this
file pins the split-module surface directly.
"""

from __future__ import annotations

import pytest

from mbforge.core.evidence import SourceEvidence
from mbforge.pipeline.activity.extraction import (
    extract_activity_measurements_from_evidence,
)
from mbforge.pipeline.activity.parsing import (
    _is_activity_table,
    _parse_simple_activity_table,
)

DOC = "activity-evidence"


def _evidence(raw_text: str, *, kind: str = "text_span") -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=DOC,
        page=1,
        bbox=(10.0, 20.0, 100.0, 40.0),
        raw_text=raw_text,
        kind=kind,
    )


# --- _is_activity_table ---


@pytest.mark.parametrize(
    "table",
    [
        "| Compound | IC50 (nM) |\n|---|---|\n| 1a | 12.5 |",
        "| Cmpd | pIC50 |\n|---|---|\n| 1 | 8.0 |",
        "| Compound | Activity |\n|---|---|\n| 1a | +++ |",
        "| Cmpd | Ki (nM) |\n|---|---|\n| 1 | 5.0 |",
        # Activity signal appears only after a leading descriptive row.
        "| Assay results | |\n| Compound | IC50 (nM) |\n|---|---|\n| 1 | 10 |",
    ],
)
def test_is_activity_table_true_for_activity_headers(table: str) -> None:
    """Tables carrying an activity header or activity unit are accepted."""
    assert _is_activity_table(table) is True, f"expected True for {table!r}"


@pytest.mark.parametrize(
    "table",
    [
        # Property / yield table — no activity header or activity unit.
        "| Compound | Yield (%) |\n|---|---|\n| 1a | 82 |",
        # Mass spectrometry charge column — looks numeric but is not activity.
        (
            "| Compound number | Analytical data | LCMS Method |\n"
            "|---|---|---|\n"
            "| E002 | LCMS: m/z 329.0 [M + H]+ | A |"
        ),
        # No separator line — not a structurally valid table.
        "| Compound | Result\n| 1 | 10 |",
        # Plain text, not a table at all.
        "Some narrative text without a table separator.",
        # Header-like line followed by plain text — malformed table.
        "| malformed |\nplain text",
        # Ambiguous "Result" header with no activity signal.
        "| Compound | Result |\n|---|---|\n| 1 | 10 |",
    ],
)
def test_is_activity_table_false_for_unrelated_tables(table: str) -> None:
    """Non-activity tables and malformed markdown are rejected."""
    assert _is_activity_table(table) is False, f"expected False for {table!r}"


# --- _parse_simple_activity_table ---


def test_parse_simple_activity_table_produces_records() -> None:
    """A small Markdown activity table yields one record per data cell."""
    table = "| Compound | IC50 (nM) |\n|---|---|\n| 1a | 12.5 |\n| 1b | 112.5 |\n"
    records = _parse_simple_activity_table(table, table_idx=0, page_num=7)
    assert len(records) == 2
    assert all(record.metric == "IC50" for record in records)
    assert [record.row_label for record in records] == ["1a", "1b"]
    assert [record.page_num for record in records] == [7, 7]
    assert [record.value_original for record in records] == [12.5, 112.5]


def test_parse_simple_activity_table_uses_default_target() -> None:
    """A provided ``default_target`` is forwarded to every record."""
    table = "| Cmpd | EC50 (nM) |\n|---|---|\n| 1 | 5.0 |\n"
    records = _parse_simple_activity_table(
        table,
        table_idx=2,
        page_num=None,
        default_target="MRGPRX2",
    )
    assert len(records) == 1
    assert records[0].target == "MRGPRX2"
    assert records[0].table_idx == 2


def test_parse_simple_activity_table_empty_for_non_activity_table() -> None:
    """Tables without an activity metric in the header produce no records."""
    table = "| Compound | Yield (%) |\n|---|---|\n| 1a | 82 |\n"
    assert _parse_simple_activity_table(table, table_idx=0, page_num=1) == []


def test_parse_simple_activity_table_empty_for_non_table() -> None:
    """Markdown without a separator line yields no records."""
    assert _parse_simple_activity_table("just some text", table_idx=0, page_num=1) == []


def test_source_evidence_prose_measurement_keeps_text_evidence_id() -> None:
    """A prose potency token is parsed from one text span without file input."""
    block = _evidence("Compound 21 showed an IC50 of < 0.1 μM.")

    measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

    assert issues == []
    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement["metric"] == "IC50"
    assert measurement["value"]["raw_text"] == "< 0.1 μM"
    assert measurement["value"]["original_value"] == 0.1
    assert measurement["value"]["canonical_value"] == 100.0
    assert measurement["value"]["operator"] == "<"
    assert measurement["evidence_ids"] == [block.evidence_id]


def test_source_evidence_table_measurements_share_table_span_id() -> None:
    """Every value in one complete table points to its single table evidence."""
    block = _evidence(
        "| Compound | IC50 (nM) | EC50 (nM) |\n"
        "|---|---|---|\n"
        "| 1 | 10 | 20 |\n"
        "| 2 | 5 | 15 |",
        kind="table_span",
    )

    measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

    assert issues == []
    assert len(measurements) == 4
    assert all(item["evidence_ids"] == [block.evidence_id] for item in measurements)
    assert len({item["measurement_id"] for item in measurements}) == 4


def test_source_evidence_complex_table_returns_issue_without_measurements() -> None:
    """An unreadable activity cell skips the whole table instead of guessing."""
    block = _evidence(
        "| Compound | IC50 (nM) |\n|---|---|\n| 1 | 10 |\n| 2 | unreadable |",
        kind="table_span",
    )

    measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

    assert measurements == []
    assert len(issues) == 1
    assert issues[0]["code"] == "complex_activity_table"
    assert issues[0]["evidence_ids"] == [block.evidence_id]

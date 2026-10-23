"""Readings carry their own location, and overlapping tables are read once.

Both regressions were found on real patents, not constructed:

1. ``ActivityMeasurement`` did not carry ``page_num``/``table_idx``/``row_idx``/
   ``col_idx`` even though the extractor knew them, so every reading reached SQL
   with no page and could not be pointed back at its PDF cell.
2. A wide table that the layout pass stored as two overlapping evidence rows was
   read twice, duplicating every cell in the overlap (CN120329282A: 28 readings
   for a 19-row table).
"""

from __future__ import annotations

from mbforge.domain.activity import ActivityMeasurement, MeasurementValue
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import TABLE, register_kinds
from mbforge.service.pipeline.activity.extraction import (
    extract_activity_measurements_from_evidence,
)

# Producer labels are registered where they are minted; declare the ones this
# module's evidence uses.
register_kinds({"text": "text", "tab": TABLE})


def _evidence(
    evidence_id: str, *, page: int, text: str, kind: str = "tab"
) -> SourceEvidence:
    return SourceEvidence(
        doc_id="doc-1",
        page=page,
        bbox=(0.0, 0.0, 1.0, 1.0),
        evidence_id=evidence_id,
        raw_text=text,
        kind=kind,
    )


TABLE = """| 化合物编号 | IC50(nM) |
| --- | --- |
| 化合物1 | 60.7 |
| 化合物7 | 39.26 |
| 化合物8 | 119 |
"""

TABLE_LONGER = (
    TABLE
    + """| 化合物32 | 83 |
| 化合物38 | 75.86 |
"""
)


def test_reading_keeps_its_own_page_and_cell() -> None:
    """A reading carries the page and cell it was printed in."""
    measurements, _ = extract_activity_measurements_from_evidence(
        [_evidence("ev-1", page=110, text=TABLE)], "doc-1"
    )

    assert len(measurements) == 3
    assert {item["page_num"] for item in measurements} == {110}
    assert {item["table_idx"] for item in measurements} == {0}
    assert [item["row_idx"] for item in measurements] == [0, 1, 2]
    assert {item["col_idx"] for item in measurements} == {1}


def test_overlapping_table_evidence_is_read_once() -> None:
    """Two evidence rows where one repeats the other's rows yield one reading each."""
    measurements, _ = extract_activity_measurements_from_evidence(
        [
            _evidence("ev-short", page=110, text=TABLE),
            _evidence("ev-long", page=110, text=TABLE_LONGER),
        ],
        "doc-1",
    )

    values = [
        item["value"]["original_value"]
        for item in measurements
        if item["value"]["original_value"] is not None
    ]
    # Five rows in the longer table; the shorter one adds no duplicate readings.
    assert values == [60.7, 39.26, 119.0, 83.0, 75.86]
    assert len(values) == len(set(values))


def test_reading_round_trips_through_its_dict() -> None:
    """The location survives serialization, so the artifact can be projected."""
    original = ActivityMeasurement(
        measurement_id="m-1",
        doc_id="doc-1",
        value=MeasurementValue(raw_text="12", original_value=12),
        page_num=7,
        table_idx=2,
        row_idx=3,
        col_idx=1,
    )

    restored = ActivityMeasurement.from_dict(original.to_dict())

    assert restored.page_num == 7
    assert restored.table_idx == 2
    assert restored.row_idx == 3
    assert restored.col_idx == 1


QUALITATIVE_TABLE = """| 化合物编号 | 抑制活性 |
| --- | --- |
| 化合物1 | ++++ |
| 化合物7 | ++ |
"""


def test_qualitative_bin_is_not_stored_as_a_number() -> None:
    """``+++`` is an ordinal bin: it must not be filed as a quantitative reading.

    A consumer that reads the bins as concentrations is wrong by orders of
    magnitude, so the kind travels with the reading instead of being inferred
    from the absent value.
    """
    measurements, _ = extract_activity_measurements_from_evidence(
        [_evidence("ev-q", page=20, text=QUALITATIVE_TABLE)], "doc-1"
    )

    assert len(measurements) == 2
    assert {item["measurement_kind"] for item in measurements} == {"qualitative"}
    assert [item["value"]["qualitative_rank"] for item in measurements] == [4, 2]
    assert all(item["value"]["original_value"] is None for item in measurements)
    assert {item["value"]["qualitative_scheme"] for item in measurements} == {"plus"}

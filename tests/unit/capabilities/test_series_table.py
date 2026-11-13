# @tested-functions render_series_table
"""The Markdown table an activity answer quotes must stay faithful to the rows.

A dropped row, a missing structure source or an unescaped pipe is a silent data
defect in the reply, not a formatting nit: this covers the whole render path in
one usage rather than per-column assertions.
"""

from __future__ import annotations

from mbforge.service.capabilities.read_sar import (
    SeriesActivity,
    SeriesMolecule,
    render_series_table,
)


def _molecule(
    name: str,
    smiles: str,
    *,
    structure_evidence_id: str = "",
    activities: list[SeriesActivity] | None = None,
) -> SeriesMolecule:
    return SeriesMolecule(
        mol_id=f"mol-{name}",
        canonical_smiles=smiles,
        name=name,
        source_doc="doc",
        structure_evidence_id=structure_evidence_id,
        structure_page=81,
        mass_check="match",
        activities=activities or [],
    )


def test_series_table_keeps_every_row_with_both_evidence_sources() -> None:
    measured = _molecule(
        "14",
        "Cn1cc2c(N)ncnc2n1",
        structure_evidence_id="structure-14",
        activities=[
            SeriesActivity(
                measurement_id="reading-1",
                metric="IC50",
                value_canonical=67.0,
                unit_canonical="nM",
                page_num=124,
                evidence_ids=["value-1"],
            ),
            SeriesActivity(
                measurement_id="reading-2",
                metric="IC50",
                value_canonical=13.4,
                unit_canonical="nM",
                operator=">",
                page_num=125,
                evidence_ids=["value-2"],
            ),
        ],
    )
    unmeasured = _molecule("1", "CCO|C", structure_evidence_id="structure-1")

    columns, rows, without_reading, table = render_series_table([measured, unmeasured])
    lines = table.splitlines()

    # One header, one separator, then one row per reading plus the row that keeps
    # an unmeasured molecule visible.
    assert columns[:6] == ["化合物", "指标", "值", "单位", "页", "SMILES"]
    assert len(lines) == 2 + 3
    assert rows == 3
    assert without_reading == ["1"]

    # Potency reads top-down inside a metric, and a censored threshold keeps its
    # operator so `>13.4` never collapses into `13.4`.
    assert "| 14 | IC50 | >13.4 | nM | 125 |" in lines[2]
    assert "| 14 | IC50 | 67 | nM | 124 |" in lines[3]

    # Both halves of the citation travel with the row, and the stored SMILES is
    # quoted once per row rather than retyped.
    assert "[[ev:value-2]]" in lines[2]
    assert "[[ev:structure-14]]" in lines[2]
    assert "`Cn1cc2c(N)ncnc2n1`" in lines[2]

    # A pipe inside a cell would split the row; it must stay inside it.
    assert "| 1 |  |  |  |  |" in lines[4]
    assert "`CCO\\|C`" in lines[4]

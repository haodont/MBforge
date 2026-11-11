"""Unit tests for ``mbforge.service.pipeline.activity.parsing.tables``.

Targets the deterministic table-parsing primitives that used to live
inside ``mbforge.service.pipeline.activity.extraction``, plus the
issue-precision contract of ``extract_activity_measurements_from_evidence``:
which published texts carry a reading and which are only legends,
glossaries, synthesis notes or OCR debris.
"""

from __future__ import annotations

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import TABLE, TEXT, register_kinds
from mbforge.service.pipeline.activity.extraction import (
    extract_activity_measurements_from_evidence,
)
from mbforge.service.pipeline.activity.parsing import (
    _is_activity_table,
    _parse_simple_activity_table,
)
from mbforge.service.pipeline.activity.parsing.tables import (
    _simple_activity_table_is_complete,
)
from mbforge.service.pipeline.layout.table_html import html_table_to_markdown

# Producer labels are registered where they are minted; declare the ones this
# module mints so the file is order-independent.
register_kinds({"text": TEXT, "tab": TABLE})

DOC = "activity-evidence"


def _evidence(raw_text: str, *, kind: str = "text", page: int = 1) -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=DOC,
        page=page,
        bbox=(10.0, 20.0, 100.0, 40.0),
        raw_text=raw_text,
        kind=kind,
    )


# --- _is_activity_table ---

_ACTIVITY_TABLES = [
    "| Compound | IC50 (nM) |\n|---|---|\n| 1a | 12.5 |",
    "| Cmpd | pIC50 |\n|---|---|\n| 1 | 8.0 |",
    "| Compound | Activity |\n|---|---|\n| 1a | +++ |",
    "| Cmpd | Ki (nM) |\n|---|---|\n| 1 | 5.0 |",
    # Activity signal appears only after a leading descriptive row.
    "| Assay results | |\n| Compound | IC50 (nM) |\n|---|---|\n| 1 | 10 |",
]

_UNRELATED_TABLES = [
    # Property / yield table — no activity header or activity unit.
    "| Compound | Yield (%) |\n|---|---|\n| 1a | 82 |",
    # Mass spectrometry charge column — looks numeric but is not activity.
    "| Compound number | Analytical data | LCMS Method |\n"
    "|---|---|---|\n"
    "| E002 | LCMS: m/z 329.0 [M + H]+ | A |",
    # No separator line — not a structurally valid table.
    "| Compound | Result\n| 1 | 10 |",
    # Plain text, not a table at all.
    "Some narrative text without a table separator.",
    # Header-like line followed by plain text — malformed table.
    "| malformed |\nplain text",
    # Ambiguous "Result" header with no activity signal.
    "| Compound | Result |\n|---|---|\n| 1 | 10 |",
]


def test_is_activity_table_accepts_headers_and_rejects_unrelated_tables() -> None:
    """Only an activity header or activity unit admits a table."""
    for table in _ACTIVITY_TABLES:
        assert _is_activity_table(table) is True, f"expected True for {table!r}"

    for table in _UNRELATED_TABLES:
        assert _is_activity_table(table) is False, f"expected False for {table!r}"


# --- _parse_simple_activity_table ---


def test_parse_simple_activity_table_records_cells_and_forwards_default_target() -> (
    None
):
    """A small Markdown activity table yields one record per data cell."""
    table = "| Compound | IC50 (nM) |\n|---|---|\n| 1a | 12.5 |\n| 1b | 112.5 |\n"
    records = _parse_simple_activity_table(table, table_idx=0, page_num=7)
    assert len(records) == 2
    assert all(record.metric == "IC50" for record in records)
    assert [record.row_label for record in records] == ["1a", "1b"]
    assert [record.page_num for record in records] == [7, 7]
    assert [record.value_original for record in records] == [12.5, 112.5]

    targeted = _parse_simple_activity_table(
        "| Cmpd | EC50 (nM) |\n|---|---|\n| 1 | 5.0 |\n",
        table_idx=2,
        page_num=None,
        default_target="MRGPRX2",
    )
    assert len(targeted) == 1
    assert targeted[0].target == "MRGPRX2"
    assert targeted[0].table_idx == 2

    # Tables without an activity metric and non-tables yield no records.
    assert (
        _parse_simple_activity_table(
            "| Compound | Yield (%) |\n|---|---|\n| 1a | 82 |\n",
            table_idx=0,
            page_num=1,
        )
        == []
    )
    assert _parse_simple_activity_table("just some text", table_idx=0, page_num=1) == []


def test_nd_cells_are_missing_not_measurements() -> None:
    """``ND`` is no data: it is counted as handled and publishes no record."""
    table = (
        "| Example | Activity | Activity |\n"
        "|---|---|---|\n"
        "| 1 | +++ | ++ |\n"
        "| 2 | +++ | ND |"
    )
    records = _parse_simple_activity_table(table, table_idx=0, page_num=42)

    assert [record.row_label for record in records] == ["1", "1", "2"]
    assert all("ND" not in record.value_text for record in records)
    assert _simple_activity_table_is_complete(table, records)


def test_example_prefix_overrides_a_compound_header() -> None:
    """``实施例 29`` under a ``化合物编号`` header is still an example label."""
    table = (
        "| 化合物编号 | IC50 (nM) | 化合物编号 | IC50 (nM) |\n"
        "|---|---|---|---|\n"
        "| 化合物1 | 10 | 实施例 29 | 29 |"
    )
    records = _parse_simple_activity_table(table, table_idx=0, page_num=94)

    assert [record.reference_type for record in records] == ["compound", "example"]
    assert [record.reference_key for record in records] == ["1", "29"]


# --- extract_activity_measurements_from_evidence: readings and gaps ---


def test_printed_positive_control_keeps_its_reading_and_explicit_endpoint() -> None:
    """CN120943813A p95 must retain the control without inventing its identity."""
    text = (
        "| 化合物编号 | MRGPRX2 拮抗剂活性IC50(nM) |\n"
        "| --- | --- |\n"
        "| 化合物7-P1 | <0.001 |\n"
        "| 化合物15 | 0.19 |\n"
        "| 化合物5 | 0.03 |\n"
        "| 化合物26 | 0.041 |\n"
        "| 阳参化合物 | 0.2 |"
    )
    readings, issues = extract_activity_measurements_from_evidence(
        [_evidence(text, kind="tab")], DOC
    )
    assert len(readings) == 5
    assert {m["metric"] for m in readings} == {"IC50"}
    assert {m["provenance"]["column_target"] for m in readings} == {"MRGPRX2"}
    assert readings[0]["value"]["raw_text"] == "<0.001"
    assert readings[0]["value"]["operator"] == "<"
    control = readings[-1]
    assert control["provenance"]["reference_raw"] == "阳参化合物"
    assert control["provenance"]["reference_type"] == "unresolved"
    assert control["provenance"]["reference_key"] is None
    assert control["mol_id"] is None and control["linking_status"] == "pending"
    assert [issue["code"] for issue in issues] == ["compound_reference_unresolved"]


def test_prose_measurement_needs_a_compound_reference_to_be_kept() -> None:
    """An attributed prose potency token is kept; an unbound one is reported."""
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

    # Chinese compound attribution must survive the same guards.
    attributed = _evidence("化合物7的IC50为20nM。")

    cn_measurements, cn_issues = extract_activity_measurements_from_evidence(
        [attributed], DOC
    )

    assert cn_issues == []
    assert len(cn_measurements) == 1
    assert cn_measurements[0]["provenance"]["reference_key"] == "7"

    # A potency value that names no compound is reported, never invented.
    unbound = _evidence("本实验测得 IC50 小于 100 nM。")

    unbound_measurements, unbound_issues = extract_activity_measurements_from_evidence(
        [unbound], DOC
    )

    assert unbound_measurements == []
    assert [issue["code"] for issue in unbound_issues] == ["activity_reference_missing"]


# (case, table) — a table whose activity cell cannot be read as published.
_REFUSED_ACTIVITY_TABLES: list[tuple[str, str]] = [
    (
        "CN121270515A lost rowspan shifts receptor headers into designation column",
        "| 化合物编号 | IC50(nM) | IC50(nM) | IC50(nM) | IC50(nM) |\n"
        "|---|---|---|---|---|\n"
        "| MRGPRX1 | MRGPRX2 | MRGPRX3 | MRGPRX4 | |\n"
        "| 实施例1 | + | ++++ | + | + |",
    ),
    (
        "unreadable cell",
        "| Compound | IC50 (nM) |\n|---|---|\n| 1 | 10 |\n| 2 | unreadable |",
    ),
    (
        # The control: a real activity header with an unreadable cell is a gap.
        "refused activity header",
        "| 化合物编号 | MRGPRX2 IP-1 IC50(nM) |\n"
        "|---|---|\n"
        "| 化合物1-P4 | unreadable |",
    ),
]

# (case, table, readable values) — a table whose cells that name no compound
# are left out, while the rows that do name one are published.
_PARTIAL_ACTIVITY_TABLES: list[tuple[str, str, list[float]]] = [
    (
        "value without designation",
        "| Compound | IC50 (nM) |\n| --- | --- |\n| 1 | 10 |\n| | 20 |",
        [10.0],
    ),
    (
        "OCR'd structure fragment as designation",
        "| Compound | pIC50 |\n| --- | --- |\n| E020 | 6.9 |\n| H3C | 6.6 |",
        [6.9],
    ),
]


def test_table_measurements_share_evidence_id_and_complex_cells_skip_the_table() -> (
    None
):
    """Every value in one table points at that table; an unreadable cell
    skips the whole table instead of guessing."""
    block = _evidence(
        "| Compound | IC50 (nM) | EC50 (nM) |\n"
        "|---|---|---|\n"
        "| 1 | 10 | 20 |\n"
        "| 2 | 5 | 15 |",
        kind="tab",
    )

    measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

    assert issues == []
    assert len(measurements) == 4
    assert all(item["evidence_ids"] == [block.evidence_id] for item in measurements)
    assert len({item["measurement_id"] for item in measurements}) == 4

    for case, table in _REFUSED_ACTIVITY_TABLES:
        block = _evidence(table, kind="tab")

        measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

        assert measurements == [], case
        assert [issue["code"] for issue in issues] == ["complex_activity_table"], case
        assert issues[0]["evidence_ids"] == [block.evidence_id], case


def test_cells_that_name_no_compound_are_reported_not_published() -> None:
    """A cell beside no compound, or beside an OCR fragment, is left out of the
    dataset and reported; the rows that do name a compound are published."""
    for case, table, values in _PARTIAL_ACTIVITY_TABLES:
        block = _evidence(table, kind="tab")

        measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

        assert [item["value"]["original_value"] for item in measurements] == values, (
            case
        )
        assert [issue["code"] for issue in issues] == ["activity_cells_unattributed"], (
            case
        )
        assert issues[0]["evidence_ids"] == [block.evidence_id], case


def test_page_split_activity_table_continuation_is_read() -> None:
    """A table that continues on the next page keeps its columns, not its header.

    CN119504738A pp.124-125 prints Table 1 as two evidence rows: the first
    carries the header, the second resumes with a data row and the separator the
    layout pass emitted for that fragment. The resumed rows are read under the
    previous header; a headerless table two pages later is not.
    """
    header = (
        "| 实施例 | 测试化合物 | IC50(nM) |\n"
        "| --- | --- | --- |\n"
        "| 1 | 化合物1 | 64.6 |\n"
        "| 2 | 化合物2 | 12.8 |"
    )
    continuation = (
        "| 23 | 化合物23 | 69.3 |\n| --- | --- | --- |\n| 24 | 化合物24 | 23.97 |"
    )
    first = _evidence(header, kind="tab", page=124)
    second = _evidence(continuation, kind="tab", page=125)
    measurements, issues = extract_activity_measurements_from_evidence(
        [first, second], DOC
    )

    # Inheriting a header is a documented continuation, not a guess: the audit
    # issue keeps both rows citable and makes silent inheritance impossible.
    assert [issue["code"] for issue in issues] == ["table_header_inherited"]
    assert issues[0]["evidence_ids"] == [first.evidence_id, second.evidence_id]
    assert [
        (item["value"]["original_value"], item["page_num"], item["evidence_ids"])
        for item in measurements
    ] == [
        (64.6, 124, [first.evidence_id]),
        (12.8, 124, [first.evidence_id]),
        (69.3, 125, [second.evidence_id]),
        (23.97, 125, [second.evidence_id]),
    ]

    # A same-shaped fragment that does not parse under the borrowed header is a
    # refusal, and a refusal must be visible: this row used to leave no trace.
    unreadable = _evidence(
        "| 23 | 化合物23 | unreadable |\n| --- | --- | --- |",
        kind="tab",
        page=125,
    )
    _, refusal = extract_activity_measurements_from_evidence([first, unreadable], DOC)
    assert [issue["code"] for issue in refusal] == ["complex_activity_table"]
    assert refusal[0]["evidence_ids"] == [first.evidence_id, unreadable.evidence_id]

    # A different table on the next page prints its own header: it is not a tail,
    # so it is neither read under the borrowed metric nor reported as a refusal
    # (the rat PK table printed beside Table 1 on p125).
    other = _evidence(
        "| 测试化合物 | Cmax (ng/mL) | AUC0-t (h*ng/mL) |\n| --- | --- | --- |\n"
        "| 化合物13 | 1207 | 14585 |",
        kind="tab",
        page=125,
    )
    other_measurements, other_issues = extract_activity_measurements_from_evidence(
        [first, other], DOC
    )
    assert [item["value"]["original_value"] for item in other_measurements] == [
        64.6,
        12.8,
    ]
    assert other_issues == []

    far = _evidence(continuation, kind="tab", page=127)
    far_measurements, far_issues = extract_activity_measurements_from_evidence(
        [first, far], DOC
    )
    assert [item["page_num"] for item in far_measurements] == [124, 124]
    assert far_issues == []


# (case, text, kind) — published text that holds no reading of its own.
_NON_READING_TEXTS: list[tuple[str, str, str]] = [
    (
        "bin definition line",
        "[0267] A: IC50 < 500 nM, B: 500 nM ≤ IC50 < 1 uM, C: 1 uM ≤ IC50 < 3 uM",
        "text",
    ),
    ("Chinese bin legend", "注：“+”：IC50>1μM", "text"),
    (
        "reagent table naming the target (MRGPRX2-CHO is a reagent, not a reading)",
        "| 试剂和耗材 | 来源 | 批号 |\n"
        "|---|---|---|\n"
        "| MRGPRX2-CHO | Gibco | 117650054 |",
        "tab",
    ),
    (
        "synthesis table listing what was made",
        "| The following compounds were synthesized using a similar method to "
        "that used in Compound E098 |\n"
        "|---|\n"
        "| Compound E098 | 42 |",
        "tab",
    ),
    (
        "OCR'd structure noise table (IL292693A p72)",
        "| NumN 0 m |\n| --- |\n| N? 0 zエN CH |",
        "tab",
    ),
    (
        "microsome incubation condition table (CN121270515A p22)",
        "| 肝微粒体 | 0.5mg·mL-1（受试化合物） |\n"
        "| --- | --- |\n"
        "| 0.2 mg·mL-1（咪达唑仑） |  |",
        "tab",
    ),
    (
        "metric definition sentence (WO2025002360A1 p13)",
        "术语“IC50”是指在测量这样的效应的分析中获得最大效应的50%抑制。",
        "text",
    ),
    (
        "Markush substituent run (KR20250121245A p12 / WO2025163462A1 p8)",
        "“”，10 .，-CF3，-CH2-CF3，-CF2H，-CC13，-CH2-CC13，-CC12H，-CF2C1，"
        "-CFH-CH3，-CF2-CH3，-CFC12卫， .",
        "text",
    ),
    (
        "claim term definition (JP2023544789A)",
        "「ハロ(C1-C₄)アルキル」、「アリール(C1-C₄)アルキル-」など、"
        "用語「アルキル」は、二価直鎖または分岐鎖炭化水素基を包含することを意図する。",
        "text",
    ),
    (
        "Chinese scale legend (WO2025002360A1 p46)",
        "活性范围表示如下：“A”表示拮抗剂活性IC50<50nM；“B”表示拮抗剂活性"
        "IC50介于50至300nM之间；“NE”表示未检测。",
        "text",
    ),
    (
        "glossary entry (CN120329282A p46)",
        "[0149] IC50:半数抑制浓度，指达到最大抑制效果一半时的浓度",
        "text",
    ),
    (
        "OCR'd abbreviation entry (JP2023544789A p86)",
        "D MF:N，N-ジメチルホルムアミド",
        "text",
    ),
    (
        "literature background, not this patent's data (US20210128561A1 p2)",
        "[0010] Tatemoto et al. have found that basic secretagogues could activate "
        "MrgX2 receptors with EC50 values between 10−4 and 10-7M in calcium assays",
        "text",
    ),
    (
        "table pointer (US20250206734A1 p42)",
        "[0355] Data obtained for the compounds of the Examples in the assays of "
        "Examples A, B and C are shown in Table 4.",
        "text",
    ),
    (
        "synthesis paragraph with OCR'd mass units (JP2023544789A p158)",
        "ＤＭＡ(2 mL)中、2 - ブロモ - N -(中間体71)(92 m g、0.2 57 m mο1)に、",
        "text",
    ),
]


def test_non_reading_texts_are_not_reported_as_activity_gaps() -> None:
    """Legends, glossaries, citations, table pointers and synthesis hold no
    reading: no measurement and no gap."""
    for case, text, kind in _NON_READING_TEXTS:
        block = _evidence(text, kind=kind)

        measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

        assert measurements == [], case
        assert issues == [], case


def test_unparseable_attributed_readings_are_still_reported_as_gaps() -> None:
    """The control: an attributed but unreadable reading must stay visible."""
    # WO2022152853A1: a mean pIC50 attributed to a list of examples.
    block = _evidence(
        "The pIC50s for each compound of this invention were averaged to determine "
        "a mean value, for a minimum of 2 experiments. For instance, the compounds "
        "of Examples 4, 25, 28 and 30 exhibited a pIC50 ≥ 8.0."
    )

    measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

    assert measurements == []
    assert {issue["code"] for issue in issues} == {
        "activity_value_unparsed",
        "activity_reference_missing",
    }

    # JP2023544789A p396: a list of examples carrying one pIC50 range.
    plural = _evidence(
        "実施例43~45、53、55、56、62、129、171、173、175~177、180、184、187、200"
        "および248の化合物は、5.5 >ρIC5 0> 4.5を示した。"
    )

    plural_measurements, plural_issues = extract_activity_measurements_from_evidence(
        [plural], DOC
    )

    assert plural_measurements == []
    assert [issue["code"] for issue in plural_issues] == ["activity_value_unparsed"]


# --- published table shapes (CN/US/KR originals) ---

_CN_SELECTIVITY_TABLE = "\n".join(
    [
        "| 化合物编号 | IC50(nM) |  |  |  |",
        "| --- | --- | --- | --- | --- |",
        "|  | MRGPRX1 | MRGPRX2 | MRGPRX3 | MRGPRX4 |",
        "| 4（化合WO2022067094物1） | ++ | +++ | ++ | ++ |",
        "| 实施例1 | 十 | ++++ | 十 | 十 |",
        "| 实施例2 | 十 | ++++ | 十 | 十 |",
    ]
)


def test_published_table_shapes_parse_spanning_and_repeated_headers() -> None:
    """Spanning metric headers with a target row, repeated (designation, value)
    pairs with printed labels, and a metric qualified by
    its substrate inside the header each yield one record per printed value; a
    structure fragment or an assay-only header yields none.
    """
    block = _evidence(_CN_SELECTIVITY_TABLE, kind="tab")

    measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

    assert len(measurements) == 12
    assert [item["provenance"]["column_target"] for item in measurements[:4]] == [
        "MRGPRX1",
        "MRGPRX2",
        "MRGPRX3",
        "MRGPRX4",
    ]
    assert {item["metric"] for item in measurements} == {"IC50"}
    assert [item["value"]["qualitative_value"] for item in measurements] == [
        "++",
        "+++",
        "++",
        "++",
        "+",
        "++++",
        "+",
        "+",
        "+",
        "++++",
        "+",
        "+",
    ]
    assert [item["value"]["qualitative_rank"] for item in measurements] == [
        2,
        3,
        2,
        2,
        1,
        4,
        1,
        1,
        1,
        4,
        1,
        1,
    ]
    # ``实施例N`` designations are not resolved to a compound key yet.
    assert {issue["code"] for issue in issues} == {"compound_reference_unresolved"}

    repeated = _evidence(
        "| 实施例编号 | IC50 (nM) | 实施例编号 | IC50 (nM) |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | 10 | 2 | 20 |",
        kind="tab",
    )

    repeated_measurements, repeated_issues = (
        extract_activity_measurements_from_evidence([repeated], DOC)
    )

    assert repeated_issues == []
    assert len(repeated_measurements) == 2
    assert [item["value"]["original_value"] for item in repeated_measurements] == [
        10.0,
        20.0,
    ]

    # OXR, US20260027089A1 p60: the spanning title precedes the real header.
    titled = html_table_to_markdown(
        '<table><tr><td colspan="3">Results for Select Compounds</td></tr>'
        "<tr><td>Compound</td><td>Structure (image)</td>"
        "<td>Human MrgprX2 Antagonist pIC50</td></tr>"
        "<tr><td>E001</td><td></td><td>6.4</td></tr>"
        "<tr><td>E002</td><td></td><td>5.1</td></tr>"
        "<tr><td>E003</td><td></td><td>7.4</td></tr></table>"
    )
    assert titled is not None
    titled_readings, titled_issues = extract_activity_measurements_from_evidence(
        [_evidence(titled, kind="tab")], DOC
    )
    assert titled_issues == []
    assert [m["value"]["original_value"] for m in titled_readings] == [6.4, 5.1, 7.4]
    assert [m["metric"] for m in titled_readings] == ["pIC50"] * 3
    assert [m["provenance"]["reference_key"] for m in titled_readings] == [
        "E001",
        "E002",
        "E003",
    ]

    # Actual SLANet shapes: explicit row/column spans must keep the target in
    # its own logical column. Existing Markdown fixtures have already lost spans.
    for html, targets in (
        (
            '<table><tr><td rowspan="2">实施例编号</td><td>MRGPRX2 抑制</td>'
            '<td rowspan="2">实施例编号</td><td>MRGPRX2 抑制</td></tr>'
            "<tr><td>活性</td><td>活性</td></tr>"
            "<tr><td>5</td><td>++++</td><td>6</td><td>++++</td></tr></table>",
            ["MRGPRX2", "MRGPRX2"],
        ),
        (
            '<table><tr><td rowspan="2">化合物编号</td><td colspan="2">IC50(nM)</td>'
            "</tr><tr><td>MRGPRX1</td><td>MRGPRX2</td></tr>"
            "<tr><td>1</td><td>12</td><td>34</td></tr></table>",
            ["MRGPRX1", "MRGPRX2"],
        ),
    ):
        markdown = html_table_to_markdown(html)
        assert markdown is not None
        span_readings, span_issues = extract_activity_measurements_from_evidence(
            [_evidence(markdown, kind="tab")], DOC
        )
        assert span_issues == []
        assert [m["provenance"].get("column_target") for m in span_readings] == targets

    # CN120329282A p113: the metric lives inside a target-qualified header, and the
    # two columns differ only by their substrate. Both facts were refused whole
    # before — no metric token was recognized at all.
    cyp = _evidence(
        "|  | CYP3A4(咪达唑仑)抑制率(%) | CYP3A4(睾酮)抑制率(%) |\n"
        "| --- | --- | --- |\n"
        "| 化合物77 | 26.3 | 31.7 |\n"
        "| 化合物46 | 16.5 | 28.4 |",
        kind="tab",
    )

    cyp_measurements, cyp_issues = extract_activity_measurements_from_evidence(
        [cyp], DOC
    )

    assert cyp_issues == []
    assert [item["metric"] for item in cyp_measurements] == ["抑制率"] * 4
    assert [item["value"]["original_value"] for item in cyp_measurements] == [
        26.3,
        31.7,
        16.5,
        28.4,
    ]
    assert {item["value"]["canonical_unit"] for item in cyp_measurements} == {"%"}
    # A measurement has no target field, so the header's own target is what keeps
    # the two substrates apart in the published provenance.
    assert [item["provenance"]["column_target"] for item in cyp_measurements] == [
        "CYP3A4 咪达唑仑",
        "CYP3A4 睾酮",
        "CYP3A4 咪达唑仑",
        "CYP3A4 睾酮",
    ]
    assert [item["provenance"]["reference_key"] for item in cyp_measurements] == [
        "77",
        "77",
        "46",
        "46",
    ]

    # CN121270515A p20 prints 6 in the blank OCR cell. Never assign it to 5:
    # the value that lost its label is reported, not read as 5's second reading.
    merged = _evidence(
        "| 实施例编号 | MRGPRX2 抑制 | 实施例编号 | MRGPRX2 抑制 |\n"
        "| --- | --- | --- | --- |\n"
        "| 5 | ++++ | | ++++ |",
        kind="tab",
    )

    merged_measurements, merged_issues = extract_activity_measurements_from_evidence(
        [merged], DOC
    )

    assert [item["value"]["qualitative_value"] for item in merged_measurements] == [
        "++++"
    ]
    assert [issue["code"] for issue in merged_issues] == ["activity_cells_unattributed"]

    # The rejected neighbours. A structure fragment is not a designation, so the
    # value beside it stays unread and the table is reported instead of guessed.
    noise = _evidence(
        "|  | MrgprX2 Antagonist pIC50 |\n| --- | --- |\n| N. HN S | 6.4 |",
        kind="tab",
    )
    noise_measurements, noise_issues = extract_activity_measurements_from_evidence(
        [noise], DOC
    )
    assert noise_measurements == []
    assert [issue["code"] for issue in noise_issues] == ["complex_activity_table"]

    # Assay-only headers state no metric: ask the model to read context rather
    # than inventing IC50 or silently omitting the table from its worklist.
    assays = _evidence(
        "| Example | MRGPRX2 FLIPR | MRGPRX2 IP1 HTRF |\n| --- | --- | --- |\n"
        "| 1 | 8.2 | 7.9 |",
        kind="tab",
    )
    assay_measurements, assay_issues = extract_activity_measurements_from_evidence(
        [assays], DOC
    )
    assert assay_measurements == []
    assert [issue["code"] for issue in assay_issues] == ["complex_activity_table"]


def test_document_legend_resolves_letter_bins_outside_the_table() -> None:
    """Letter bins are defined once per document, outside the table using them."""
    table = _evidence(
        "| Compound | IC50 (nM) |\n| --- | --- |\n| 7 | A |\n| 8 | B |",
        kind="tab",
    )
    declared = _evidence("注：“A”：IC50>1μM；“B”：100nM<IC50<1μM")

    without, _ = extract_activity_measurements_from_evidence([table], DOC)
    with_legend, _ = extract_activity_measurements_from_evidence([declared, table], DOC)

    assert [item["value"]["qualitative_scheme"] for item in without] == [
        "letter_unresolved",
        "letter_unresolved",
    ]
    assert [item["value"]["qualitative_scheme"] for item in with_legend] == [
        "legend",
        "legend",
    ]
    assert with_legend[0]["value"]["qualitative_label"] == "IC50>1μM"


#: US20210128561A1 p51 prints its SAR table the way a US application does: the
#: assay name in a spanning title row, the metric in the row below it, values
#: with an error term (``11.6 ± 3.7``), censored readings (``>100 (4%)``), and
#: compound numbers from a letter series (``A-1``, ``B-40``).
_US_SAR_TABLE = "\n".join(
    [
        "|  | β-arrestin assay (CHO β-arrestin human MrgX4 "
        "| calcium assay (LN229 cells recombinantly expressing human wildtype |",
        "| --- | --- | --- |",
        "|  | L83S) IC50 ± [μM]a (% inhibition ± SEM)c | IC50 ± SEM [μM]a |",
        "|  |  | (% inhibition ± SEM)d |",
        "| A-1 | >100 (4%) |  |",
        "| A-8 | 11.6 ± 3.7 | 2.89 ± 0.24 |",
        "|  | 2.42 ± 0.22 | 0.683 ± 0.174 |",
        "| B-32 | >100 (40%) >100 (45%) |  |",
        "| B-40 | 0.0225 ± 0.0024 | 0.000420 ± 0.000054 |",
    ]
)


def test_us_published_sar_table_yields_one_reading_per_printed_value() -> None:
    """A US SAR table is read: the metric row under the assay title, ``± SEM``
    values, censored readings, and letter-series compound numbers.

    The cells that named no compound and the cell that held two readings merged
    into one are left out and reported; every printed value beside a compound
    becomes one reading.
    """
    block = _evidence(_US_SAR_TABLE, kind="tab")

    measurements, issues = extract_activity_measurements_from_evidence([block], DOC)

    assert [item["provenance"]["reference_key"] for item in measurements] == [
        "A-1",
        "A-8",
        "A-8",
        "B-40",
        "B-40",
    ]
    assert {item["metric"] for item in measurements} == {"IC50"}
    assert [item["value"]["original_value"] for item in measurements] == [
        100.0,
        11.6,
        2.89,
        0.0225,
        0.00042,
    ]
    assert {item["value"]["original_unit"] for item in measurements} == {"μM"}
    # The censored reading keeps its comparator; the error term is not a value.
    assert [item["value"]["operator_original"] for item in measurements] == [
        ">",
        "=",
        "=",
        "=",
        "=",
    ]
    assert {item["provenance"]["column_target"] for item in measurements} == {
        "β-arrestin CHO β-arrestin human MrgX4 L83S",
        "calcium LN229 cells recombinantly expressing human wildtype",
    }
    assert [issue["code"] for issue in issues] == ["activity_cells_unattributed"]
    assert "no_designation" in issues[0]["message"]

from __future__ import annotations

from collections.abc import Iterable

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import TABLE, TEXT, register_kinds
from mbforge.domain.paragraphs import (
    group_paragraphs,
    indent_grid,
    paragraph_anchors,
)

register_kinds({"text": TEXT, "sec": TEXT, "head": TEXT, "tab": TABLE, "figno": TEXT})


def _row(
    page: int,
    top: float,
    raw_text: str,
    *,
    kind: str = "text",
    left: float = 10.0,
    right: float = 500.0,
) -> SourceEvidence:
    """One evidence region; ``top`` is its top edge, so larger reads first."""
    return SourceEvidence.create(
        doc_id="doc",
        page=page,
        bbox=(left, top - 10.0, right, top),
        raw_text=raw_text,
        kind=kind,
    )


def _rows(level_lefts: Iterable[tuple[float, str]]) -> list[SourceEvidence]:
    """Three regions per level, so the level is more than a stray edge."""
    rows: list[SourceEvidence] = []
    top = 700.0
    for left, text in level_lefts:
        for index in range(3):
            rows.append(_row(1, top, f"{text} {index}", left=left))
            top -= 10.0
    return rows


def test_numbered_paragraph_absorbs_its_cross_page_continuation() -> None:
    rows = [
        _row(2, 700.0, "[0003] MRGX2 is Gq-coupled and induces … mast cells (D."),
        _row(3, 800.0, "Fujisawa et al., J Allergy Clin Immunol …)."),
        _row(3, 600.0, "[0004] MRGX2 is potentially involved in host defense."),
    ]

    numbered = [p for p in group_paragraphs(rows) if p.number is not None]

    assert [p.number for p in numbered] == ["0003", "0004"]
    first = numbered[0]
    assert first.page == 2
    assert first.text == (
        "[0003] MRGX2 is Gq-coupled and induces … mast cells (D. "
        "Fujisawa et al., J Allergy Clin Immunol …)."
    )
    assert len(first.evidence_ids) == 2
    assert first.starts_at(rows[0].evidence_id)
    assert not first.starts_at(rows[1].evidence_id)


def test_section_heading_is_not_absorbed_by_the_paragraph_above_it() -> None:
    rows = [
        _row(2, 700.0, "[0001] A first paragraph."),
        _row(2, 600.0, "BACKGROUND OF THE INVENTION", kind="sec"),
        _row(2, 500.0, "[0002] A second paragraph."),
    ]

    paragraphs = group_paragraphs(rows)

    assert [p.text for p in paragraphs] == [
        "[0001] A first paragraph.",
        "BACKGROUND OF THE INVENTION",
        "[0002] A second paragraph.",
    ]
    assert [p.number for p in paragraphs] == ["0001", None, "0002"]


def test_figure_label_between_prose_fragments_is_not_absorbed() -> None:
    rows = [
        _row(
            2,
            700.0,
            "[0006] One aspect of the invention provides a compound of Formula 1:",
        ),
        _row(2, 600.0, "1"),
        _row(
            2,
            500.0,
            "or a tautomer thereof, or a pharmaceutically acceptable salt thereof.",
        ),
    ]

    numbered = [p for p in group_paragraphs(rows) if p.number is not None]

    assert len(numbered) == 1
    assert numbered[0].text == (
        "[0006] One aspect of the invention provides a compound of Formula 1: "
        "or a tautomer thereof, or a pharmaceutically acceptable salt thereof."
    )
    assert "1 " not in numbered[0].text


def test_document_without_markers_keeps_one_paragraph_per_row() -> None:
    rows = [
        _row(1, 700.0, "First line."),
        _row(1, 600.0, "Second line."),
    ]

    paragraphs = group_paragraphs(rows)

    assert [p.text for p in paragraphs] == ["First line.", "Second line."]
    assert [p.number for p in paragraphs] == [None, None]
    assert len({p.paragraph_id for p in paragraphs}) == 2


def test_indent_grid_reads_levels_from_left_edges_and_rejects_strays() -> None:
    rows = _rows([(85.0, "body"), (125.0, "(a) item"), (160.0, "deeper")])
    rows.append(_row(1, 100.0, "A-4"))  # a lone left edge, not a level

    grid = indent_grid(rows)

    assert grid.levels == (85.0, 125.0, 160.0)
    assert grid.level_of(126.0) == 1
    assert grid.level_of(300.0) == -1


def test_sub_items_at_a_deeper_left_edge_become_their_own_lines() -> None:
    rows = [
        _row(1, 700.0, "[0006] One aspect of the invention provides:", left=85.0),
        _row(1, 600.0, "(a) C1-4 alkyl which is substituted", left=125.0),
        _row(1, 500.0, "(b) a cyclic group selected from", left=125.0),
    ]

    paragraph = group_paragraphs(rows)[0]

    assert [(line.level, line.text) for line in paragraph.lines] == [
        (0, "[0006] One aspect of the invention provides:"),
        (1, "(a) C1-4 alkyl which is substituted"),
        (1, "(b) a cyclic group selected from"),
    ]


def test_same_level_fragment_continues_the_line_above_it() -> None:
    rows = [
        _row(1, 700.0, "[0006] One aspect provides a compound", left=85.0),
        _row(1, 600.0, "which is substituted at R¹.", left=85.0),
    ]

    paragraph = group_paragraphs(rows)[0]

    assert [(line.level, line.text) for line in paragraph.lines] == [
        (0, "[0006] One aspect provides a compound which is substituted at R¹.")
    ]


def test_centred_block_reads_as_a_heading() -> None:
    rows = _rows([(85.0, "body")])
    rows.append(
        _row(1, 400.0, "FIELD OF THE INVENTION", kind="sec", left=227.0, right=369.0)
    )

    paragraphs = group_paragraphs(rows)

    heading = next(p for p in paragraphs if p.lines[0].text == "FIELD OF THE INVENTION")
    assert heading.centred is True
    assert heading.number is None
    assert all(not p.centred for p in paragraphs if p is not heading)


def test_paragraph_anchors_report_line_and_level() -> None:
    rows = [
        _row(1, 700.0, "[0006] One aspect provides:", left=85.0),
        _row(1, 600.0, "(a) C1-4 alkyl", left=125.0),
    ]

    anchors = paragraph_anchors(group_paragraphs(rows))

    head = anchors[rows[0].evidence_id]
    item = anchors[rows[1].evidence_id]
    assert (head.line, head.level, head.start) == (0, 0, True)
    assert (item.line, item.level, item.start) == (1, 1, False)
    assert head.paragraph_id == item.paragraph_id
    assert head.number == "0006"

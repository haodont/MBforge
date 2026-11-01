"""Tests for the SQL-evidence section parser (unified PatentStage)."""

from __future__ import annotations

import pytest

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import IMAGE, TEXT, register_kinds
from mbforge.service.pipeline.patent.sections import (
    match_assay_heading,
    match_section_heading,
    parse_source_evidence_sections,
)

# Producer labels are registered where they are minted; declare the ones this
# module mints so the file is order-independent.
register_kinds({"text": TEXT, "figcx": IMAGE})

DOC = "doc-sections"


def _block(
    page: int,
    raw_text: str,
    *,
    kind: str = "text",
    bbox: tuple[float, float, float, float] = (10.0, 20.0, 30.0, 40.0),
) -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=DOC,
        page=page,
        bbox=bbox,
        raw_text=raw_text,
        kind=kind,
    )


# (text, expected heading number or None) — locale and format variants of the
# same heading fact; prose that merely starts like a label is not a heading.
_HEADING_CASES = [
    # ``实施例5N-((…)`` prepares compound 5 — ``N`` starts the chemical name.
    ("实施例5N-((1R,3S)-3-氨基环己基)甲酰胺的合成", "5"),
    ("Example 1a—Synthesis of compound 9", "1a"),
    # US filings mark assay sections with lettered examples.
    ("Example A. MRGPRX2 FLIPR Calcium Mobilization Assay", "A"),
    # JP filings label examples 実施例; the label names the same fact.
    ("実施例1", "1"),
    # The native text layer splits a number into digits and uses full-width
    # digits; the stored print stays verbatim, the token is normalized.
    ("実施例 1 0 3", "103"),
    ("実施例1 04", "104"),
    # A range names more than one example, so it is not one section.
    ("実施例２および3", None),
    ("Examples of 6,6-fused heteroaryl groups include quinolinyl", None),
]


def test_section_heading_recognition_covers_locales_and_prose() -> None:
    """Heading matchers bound the number; prose labels are not headings."""
    for text, expected_number in _HEADING_CASES:
        heading = match_section_heading(text)
        if expected_number is None:
            assert heading is None, text
        else:
            assert heading is not None, text
            assert heading.group("num") == expected_number, text

    assert (
        match_assay_heading("3. 稳定性测定步骤a. 将198 μL肝细胞移液到96孔平板") is None
    )

    # A numbered assay heading carries the assay its values belong to.
    blocks = [
        _block(
            19, "(一)本发明化合物对MRGPRX2的抑制活性", bbox=(10.0, 60.0, 40.0, 75.0)
        ),
        _block(19, "1. 材料与仪器", bbox=(10.0, 50.0, 40.0, 65.0)),
        _block(
            20, "(二)本发明化合物对MRGPRX亚型的选择性", bbox=(10.0, 60.0, 40.0, 75.0)
        ),
    ]
    sections = parse_source_evidence_sections(blocks, DOC)

    assert [section.kind for section in sections] == ["bioassay", "bioassay"]
    assert "抑制活性" in sections[0].title


def test_segments_evidence_into_sections_on_headings() -> None:
    """Headings cut the evidence into sections; page ranges and ids follow."""
    no_headings = [_block(1, "说明文字。"), _block(1, "另一种说法。")]
    assert parse_source_evidence_sections(no_headings, DOC) == []

    blocks = [
        _block(1, "实施例1：化合物1的合成。", bbox=(10.0, 60.0, 40.0, 75.0)),
        _block(1, "将中间体加入反应瓶。", bbox=(10.0, 50.0, 40.0, 65.0)),
        _block(1, "", kind="figcx"),
        _block(2, "实施例2：按实施例1方法制备化合物2。", bbox=(10.0, 60.0, 40.0, 75.0)),
    ]
    sections = parse_source_evidence_sections(blocks, DOC)
    assert len(sections) == 2
    first, second = sections
    assert first.title == "实施例1：化合物1的合成。"
    assert first.kind == "example"
    assert (first.page_start, first.page_end) == (1, 1)
    assert first.evidence_ids == [blocks[0].evidence_id, blocks[1].evidence_id]
    assert first.title_evidence_ids == [blocks[0].evidence_id]
    assert "将中间体加入反应瓶。" in first.raw_text
    assert second.title == "实施例2：按实施例1方法制备化合物2。"
    assert (second.page_start, second.page_end) == (2, 2)
    assert second.evidence_ids == [blocks[3].evidence_id]
    assert second.title_evidence_ids == [blocks[3].evidence_id]

    # Published text prefixes headings with ``[NNNN]``; a body phrase is not cut.
    published = [
        _block(13, "[0095] 实施例1N-((1R,3S)-3-氨基环己基)甲酰胺的合成"),
        _block(14, "[0143]实施例7"),
        _block(18, "Example 2—Screening of Compounds"),
        _block(19, "实施例1方法。"),
    ]
    sections = parse_source_evidence_sections(published, DOC)
    assert [section.kind for section in sections] == ["example"] * 3
    assert [section.page_start for section in sections] == [13, 14, 18]
    assert sections[0].title.startswith("实施例1")
    assert sections[1].title == "实施例7"
    assert sections[2].title.startswith("Example 2")


def test_rejects_mixed_doc_id():
    blocks = [_block(1, "实施例1：化合物1的合成。")]
    foreign = SourceEvidence.create(
        doc_id="other", page=2, bbox=(1.0, 2.0, 3.0, 4.0), raw_text="实施例2："
    )
    with pytest.raises(ValueError, match="doc_id"):
        parse_source_evidence_sections([*blocks, foreign], DOC)

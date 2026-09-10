"""Tests for the SQL-evidence section parser (unified PatentStage)."""

from __future__ import annotations

import pytest

from mbforge.core.evidence import SourceEvidence
from mbforge.pipeline.sections import parse_source_evidence_sections

DOC = "doc-sections"


def _block(
    page: int,
    raw_text: str,
    *,
    kind: str = "text_span",
    coref: str = "",
    bbox: tuple[float, float, float, float] = (10.0, 20.0, 30.0, 40.0),
) -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=DOC,
        page=page,
        bbox=bbox,
        raw_text=raw_text,
        kind=kind,
        coref=coref,
    )


def test_segments_sql_blocks_on_headings_and_keeps_evidence():
    blocks = [
        _block(1, "实施例1：化合物1的合成。", bbox=(10.0, 60.0, 40.0, 75.0)),
        _block(1, "将中间体加入反应瓶。", bbox=(10.0, 50.0, 40.0, 65.0)),
        _block(1, "", kind="image_region", coref="storage/x/images/a.png"),
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


def test_empty_without_headings():
    blocks = [_block(1, "说明文字。"), _block(1, "另一种说法。")]
    assert parse_source_evidence_sections(blocks, DOC) == []


def test_rejects_mixed_doc_id():
    blocks = [_block(1, "实施例1：化合物1的合成。")]
    foreign = SourceEvidence.create(
        doc_id="other", page=2, bbox=(1.0, 2.0, 3.0, 4.0), raw_text="实施例2："
    )
    with pytest.raises(ValueError, match="doc_id"):
        parse_source_evidence_sections([*blocks, foreign], DOC)

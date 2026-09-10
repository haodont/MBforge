"""Unit tests for the layout-blocks side of the document overlay."""

from __future__ import annotations

from mbforge.pipeline.detection.types import DetectionSource, NormalizedMolecule
from mbforge.pipeline.extract_text import ExtractedDocument, PageContent, TextSpan
from mbforge.services.documents.pdf_layout import (
    build_document_overlay,
    load_document_bboxes,
)
from tests.unit.v2_artifact_helpers import publish_v2_run

PAGE_H = 300.0  # synthetic source-PDF page height (pt)


def _save_synthetic(tmp_path, doc_id: str = "doc-1") -> None:
    """Write a synthetic extract artifact whose spans are top-left origin."""
    extracted = ExtractedDocument(
        raw_text="...",
        page_count=2,
        parser="pymupdf+ocr",
        pages=[
            PageContent(
                page_num=1,
                text="title",
                text_spans=[
                    TextSpan(
                        text="(19)国家知识产权局",
                        bbox=(71.37, 48.26, 197.03, 62.26),
                        block_type=0,
                    ),
                    TextSpan(
                        text="A | B",
                        bbox=(20.0, 70.0, 80.0, 90.0),
                        block_type=2,
                    ),
                    TextSpan(text="", bbox=(450.9, 243.9, 524.4, 277.6), block_type=1),
                ],
                figure_bboxes=[(154.87, 249.17, 232.62, 290.83)],
            ),
            PageContent(page_num=2, text="claims"),
        ],
    )
    publish_v2_run(
        tmp_path,
        doc_id,
        "run-1",
        extracted,
        [],
        width=600.0,
        height=PAGE_H,
    )


def _save_detections(
    tmp_path, doc_id: str, candidates: list[NormalizedMolecule], stats: dict
) -> None:
    page_numbers = {
        detection.page + 1
        for candidate in candidates
        for detection in candidate.detections
        if detection.page is not None and detection.bbox is not None
    }
    page_count = max(page_numbers, default=1)
    extracted = ExtractedDocument(
        raw_text="",
        page_count=page_count,
        pages=[
            PageContent(page_num=page, text="") for page in range(1, page_count + 1)
        ],
    )
    publish_v2_run(
        tmp_path,
        doc_id,
        "run-2",
        extracted,
        candidates,
        stats,
        width=600.0,
        height=PAGE_H,
    )


def test_overlay_blocks_read_sql_evidence_without_flip(tmp_path) -> None:
    """Blocks come straight from SQL: no y-flip, no Extract branch rebuild."""
    _save_synthetic(tmp_path)
    result = build_document_overlay(str(tmp_path), "doc-1", "/p.pdf")
    blocks = result["blocks"]
    texts = [b for b in blocks if b["block_type"] == "text"]
    tables = [b for b in blocks if b["block_type"] == "table"]
    images = [b for b in blocks if b["block_type"] == "image"]
    # The Join already normalized coordinates, so the reader passes them through.
    assert texts[0]["bbox"] == (71.37, 48.26, 197.03, 62.26)
    assert texts[0]["content"] == "(19)国家知识产权局"
    assert texts[0]["page"] == 1
    assert tables[0]["content"] == "A | B"
    # The blank image-type span and the figure region both become image blocks,
    # still in the SQL reading order (top of the page first).
    assert [b["page"] for b in images] == [1, 1]
    assert [b["bbox"] for b in images] == [
        (154.87, 249.17, 232.62, 290.83),
        (450.9, 243.9, 524.4, 277.6),
    ]
    assert all(b["content"] is None for b in images)
    assert [b["index"] for b in blocks] == list(range(len(blocks)))
    assert result["from_cache"] is True


def test_overlay_blocks_read_joined_evidence_rows(tmp_path) -> None:
    doc_id = "doc-v2"
    extracted = ExtractedDocument(
        raw_text="text",
        page_count=1,
        pages=[
            PageContent(
                page_num=1,
                text="text",
                text_spans=[TextSpan("text", (10.0, 20.0, 30.0, 50.0))],
            )
        ],
    )
    publish_v2_run(tmp_path, doc_id, "run-1", extracted, [], width=200.0, height=300.0)

    result = build_document_overlay(str(tmp_path), doc_id, "/p.pdf")

    assert result["blocks"][0]["bbox"] == (10.0, 20.0, 30.0, 50.0)


def test_overlay_missing_doc_yields_empty_blocks(tmp_path) -> None:
    result = build_document_overlay(str(tmp_path), "nope", "/p.pdf")
    assert result["blocks"] == []
    assert result["from_cache"] is True


def test_load_document_bboxes_reports_stage_coverage(tmp_path) -> None:
    # The artifact-side reader still backs the molecule reverse lookup
    # (services.molecule.queries); the viewer overlay reads SQL instead.
    _save_detections(
        tmp_path,
        "doc-1",
        [
            NormalizedMolecule(
                canonical_smiles="CCO",
                esmiles="CCO",
                name="EtOH",
                sources=["image"],
                detections=[
                    DetectionSource(
                        source="image",
                        page=1,
                        bbox=(100.0, 200.0, 200.0, 300.0),
                        image_path="crops/etoh.png",
                        confidence=0.81,
                        conf_moldet=0.9,
                    )
                ],
            )
        ],
        {"molecule_count": 1},
    )
    extracted, candidates = load_document_bboxes(str(tmp_path), "doc-1")
    assert extracted is not None
    assert candidates is not None
    assert candidates[0].canonical_smiles == "CCO"
    assert candidates[0].detections[0].page == 1

    assert load_document_bboxes(str(tmp_path), "nope") == (None, None)

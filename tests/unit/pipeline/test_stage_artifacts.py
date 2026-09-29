"""Tests for the SQL source-evidence mint and its readers.

Extract is the single producer: it mints ``SourceEvidence`` rows from the
layout regions plus the molecule pass and persists them. There is no branch
artifact, so these tests drive :func:`mint_evidence` and the SQL readers.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mbforge.db.source_evidence import persist_source_evidence
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource, ExtractionResult
from mbforge.service.pipeline.artifacts import (
    load_detections,
    load_extracted,
    mint_evidence,
)
from mbforge.service.pipeline.artifacts.evidence_models import PageFrame
from mbforge.service.pipeline.artifacts.hydration import (
    hydrate_context_from_evidence,
)
from mbforge.service.pipeline.extract.text import (
    ExtractedDocument,
    PageContent,
    TextSpan,
)
from mbforge.service.pipeline.run.context import PipelineContext

DOC = "doc-artifacts"


def _layout_extracted() -> ExtractedDocument:
    """An Extract document authored by the local layout producer."""
    text_bbox = (1.0, 2.0, 3.0, 4.0)
    chem_bbox = (10.0, 20.0, 30.0, 40.0)
    page = PageContent(
        page_num=1,
        text="Compound 1",
        regions=[
            {
                "region_id": "r0",
                "kind": "text",
                "type": "text",
                "bbox": list(text_bbox),
                "score": 0.9,
                "reading_order": 0,
                "source": "merged",
                "text": "Compound 1",
            },
            {
                "region_id": "r1",
                "kind": "chem",
                "type": "image",
                "bbox": list(chem_bbox),
                "score": 0.8,
                "reading_order": 1,
                "source": "layout_hiro",
                "text": "",
            },
        ],
        # The producer also derives these legacy views; they must not be minted
        # a second time.
        text_spans=[TextSpan("Compound 1", text_bbox, 0)],
        figure_bboxes=[chem_bbox],
    )
    return ExtractedDocument(
        raw_text="Compound 1",
        page_count=1,
        parser="layout",
        pages=[page],
        ocr_stats={},
    )


def _candidate() -> Molecule:
    detection = DetectionSource(
        source="image",
        page=0,
        bbox=(10.0, 20.0, 30.0, 40.0),
        image_path="crops/a.png",
        confidence=0.9,
        conf_moldet=0.95,
    )
    return Molecule(
        canonical_smiles="CCO",
        esmiles="CCO<sep>",
        name="EtOH",
        sources=["image"],
        detections=[detection],
        status="pending",
        properties={"ocr_labels": ["4A"]},
    )


def _result(candidate: Molecule | None = None) -> ExtractionResult:
    candidate = candidate or _candidate()
    detection = candidate.detections[0]
    return ExtractionResult(
        smiles=candidate.canonical_smiles,
        esmiles=candidate.esmiles,
        name=candidate.name,
        moldet_conf=detection.conf_moldet,
        bbox_pdf=detection.bbox,
        page_idx=detection.page,
        mol_img_path=detection.image_path,
        properties=dict(candidate.properties),
    )


def _frames() -> list[PageFrame]:
    return [PageFrame(page=1, width=100.0, height=100.0)]


def _archive_crop(tmp_path: Path) -> None:
    crop = tmp_path / "storage" / DOC / "crops" / "a.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"png")


def _mint(
    tmp_path: Path,
    *,
    extracted: ExtractedDocument | None = None,
    results: list[ExtractionResult] | None = None,
) -> list[SourceEvidence]:
    return mint_evidence(
        extracted if extracted is not None else _layout_extracted(),
        _frames(),
        list(results or []),
        doc_id=DOC,
        library_root=tmp_path,
    )


def test_mint_mints_layout_regions_under_the_detector_kind(tmp_path: Path) -> None:
    """Typed regions become evidence under their own label, exactly once."""
    evidence = _mint(tmp_path)

    assert {item.kind: item.bbox for item in evidence} == {
        "text": (1.0, 2.0, 3.0, 4.0),
        "chem": (10.0, 20.0, 30.0, 40.0),
    }
    # A region with no recognized text is still a legal row.
    chem = next(item for item in evidence if item.kind == "chem")
    assert chem.raw_text == ""


def test_mint_orders_layout_regions_by_reading_order(tmp_path: Path) -> None:
    """Column order beats the raster order for layout-authored evidence."""
    extracted = _layout_extracted()
    left = (10.0, 5.0, 40.0, 15.0)  # left column — later in raster order
    right = (50.0, 10.0, 90.0, 20.0)  # right column — earlier in raster order
    extracted.pages[0].regions = [
        {
            "region_id": "right",
            "kind": "text",
            "type": "text",
            "bbox": list(right),
            "score": 0.9,
            "reading_order": 1,
            "source": "merged",
            "text": "right",
        },
        {
            "region_id": "left",
            "kind": "text",
            "type": "text",
            "bbox": list(left),
            "score": 0.9,
            "reading_order": 0,
            "source": "merged",
            "text": "left",
        },
    ]
    extracted.pages[0].text_spans = []
    extracted.pages[0].figure_bboxes = []

    evidence = _mint(tmp_path, extracted=extracted)

    assert [item.bbox for item in evidence] == [left, right]


def test_mint_keeps_one_row_per_location(tmp_path: Path) -> None:
    """A location *is* the evidence ID, so two claims on one box collapse.

    The stronger claim keeps its ``kind``; the loser's content is folded in
    rather than dropped.
    """
    _archive_crop(tmp_path)
    candidate = _candidate()
    candidate.detections[0] = replace(
        candidate.detections[0],
        bbox=(1.0, 2.0, 3.0, 4.0),  # the text region's rect
    )

    evidence = _mint(tmp_path, results=[_result(candidate)])

    locations = [(item.page, item.bbox) for item in evidence]
    assert len(locations) == len(set(locations)), "one row per location"
    assert not any(item.kind == "text" for item in evidence)
    molecule = next(item for item in evidence if item.kind == "molecule")
    assert molecule.raw_text, "the winner keeps content"


def test_mint_keeps_the_content_bearing_molecule_over_an_overlapping_bare_region(
    tmp_path: Path,
) -> None:
    """An overlapping claim without content never displaces one that has it.

    A cross-model layout region re-typed to a molecule carries MolDet's own
    geometry but no payload, and its box never matches the molecule pass'
    exactly (different render DPI). Letting it win would drop the SMILES.
    """
    _archive_crop(tmp_path)
    extracted = _layout_extracted()
    # R3: the ``chem`` figure region becomes the molecule MolDet found in it,
    # with the slightly larger box the layout render produces.
    extracted.pages[0].regions[1].update(
        {"kind": "molecule", "type": "molecule", "bbox": [9.5, 19.5, 30.5, 40.5]}
    )
    candidate = _candidate()
    candidate.detections[0] = replace(
        candidate.detections[0], bbox=(10.0, 20.0, 30.0, 40.0)
    )

    evidence = _mint(tmp_path, extracted=extracted, results=[_result(candidate)])

    molecules = [item for item in evidence if item.kind == "molecule"]
    assert len(molecules) == 1
    assert molecules[0].raw_text, "the content-bearing molecule keeps its payload"
    assert molecules[0].bbox == (10.0, 20.0, 30.0, 40.0)


def test_mint_requires_archived_molecule_crop(tmp_path: Path) -> None:
    """A molecule row may not reference a crop that was never archived."""
    with pytest.raises(ValueError, match="not archived"):
        _mint(tmp_path, results=[_result()])


def test_molecule_round_trip_preserves_markush_layer_fields(tmp_path: Path) -> None:
    """The SQL-backed reload keeps Layer 1 and Markush metadata distinct."""
    _archive_crop(tmp_path)
    candidate = _candidate()
    candidate.esmiles = "CCO<sep>R1-definition"
    candidate.properties = {"markush": True, "groups": "R1=alkyl"}

    persist_source_evidence(tmp_path, _mint(tmp_path, results=[_result(candidate)]))

    restored, _ = load_detections(tmp_path, DOC)

    assert len(restored) == 1
    assert restored[0].canonical_smiles == "CCO"
    assert restored[0].esmiles == "CCO<sep>R1-definition"
    assert restored[0].properties["markush"] is True
    assert restored[0].properties["groups"] == "R1=alkyl"


def test_load_extracted_reads_minted_pages(tmp_path: Path) -> None:
    persist_source_evidence(tmp_path, _mint(tmp_path))

    restored = load_extracted(tmp_path, DOC)

    assert restored is not None
    assert restored.parser == "layout"
    assert restored.page_count == 1
    assert restored.pages[0].page_num == 1
    assert restored.pages[0].text_spans[0].text == "Compound 1"


def test_hydrate_context_fills_missing_fields(tmp_path: Path) -> None:
    _archive_crop(tmp_path)
    persist_source_evidence(tmp_path, _mint(tmp_path, results=[_result()]))
    document_md = tmp_path / "storage" / DOC / "document.md"
    document_md.write_text("# T\n", encoding="utf-8")

    ctx = PipelineContext(
        pdf_path=tmp_path / "x.pdf", library_root=tmp_path, doc_id=DOC, run_id="run-1"
    )
    hydrate_context_from_evidence(ctx)

    assert ctx.extracted is not None
    assert ctx.extracted.page_count == 1
    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].properties.get("ocr_labels") == ["4A"]
    assert ctx.document_md_path == document_md


def test_source_evidence_rejects_page_only_evidence() -> None:
    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.create(
            doc_id=DOC,
            page=1,
            bbox=None,  # type: ignore[arg-type]
            raw_text="legacy",
        )

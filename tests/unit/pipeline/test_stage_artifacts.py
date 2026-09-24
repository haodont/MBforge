"""Tests for the raw Extract branch artifact and SQL source evidence."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from mbforge.adapters.persistence.source_evidence import persist_source_evidence
from mbforge.application.pipeline.artifacts import (
    build_extract_artifact,
    hydrate_context_from_artifacts,
    join_evidence_artifacts,
    load_detections,
    load_document_evidence,
    load_extract_branch,
    load_extracted,
    save_extract_branch,
)
from mbforge.application.pipeline.artifacts.evidence_models import (
    DocumentEvidenceArtifact,
    PageFrame,
)
from mbforge.application.pipeline.artifacts.staging import publish_run
from mbforge.application.pipeline.extract.text import (
    ExtractedDocument,
    PageContent,
    TextSpan,
)
from mbforge.application.pipeline.run.context import PipelineContext
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource, ExtractionResult

DOC = "doc-artifacts"


def _extracted() -> ExtractedDocument:
    page = PageContent(
        page_num=1,
        text="hello world",
        ocr_dpi=200,
        text_spans=[TextSpan("hello", (1.0, 2.0, 3.0, 4.0), 0)],
        figure_bboxes=[(10.0, 20.0, 30.0, 40.0)],
        ocr_backend="layout:stub",
        ocr_attempts=1,
        ocr_elapsed_ms=123,
        ocr_error=None,
    )
    return ExtractedDocument(
        raw_text="hello world",
        page_count=1,
        parser="pymupdf",
        title="T",
        pages=[page],
        ocr_stats={"pages": 1},
    )


def _candidate() -> Molecule:
    detection = DetectionSource(
        source="image",
        page=0,
        bbox=(50.0, 60.0, 70.0, 80.0),
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
        reject_reason=None,
        properties={"ocr_labels": ["4A"]},
    )


def _result(candidate: Molecule | None = None) -> ExtractionResult:
    candidate = candidate or _candidate()
    detection = candidate.detections[0]
    return ExtractionResult(
        esmiles=candidate.esmiles,
        smiles=candidate.canonical_smiles,
        name=candidate.name,
        source=detection.source,
        moldet_conf=detection.conf_moldet,
        bbox_pdf=detection.bbox,
        page_idx=detection.page,
        mol_img_path=detection.image_path,
        status=candidate.status,
        properties=dict(candidate.properties),
    )


def _frames() -> list[PageFrame]:
    return [PageFrame(page=1, width=100.0, height=100.0, rotation=0)]


def _build(
    tmp_path: Path,
    *,
    run_id: str = "run-1",
    extracted: ExtractedDocument | None = None,
    results: list[ExtractionResult] | None = None,
    molecule_stats: dict | None = None,
    frames: list[PageFrame] | None = None,
):
    """Build the one Extract artifact, with molecules folded in."""
    return build_extract_artifact(
        DOC,
        run_id,
        extracted if extracted is not None else _extracted(),
        frames if frames is not None else _frames(),
        results=results or [],
        molecule_stats=molecule_stats,
        library_root=tmp_path,
    )


def _archive_crop(tmp_path: Path) -> None:
    crop = tmp_path / "storage" / DOC / "crops" / "a.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"png")


def _publish_joined_evidence(tmp_path: Path, run_id: str = "run-1") -> None:
    extracted = _build(
        tmp_path,
        run_id=run_id,
        results=[_result()],
        molecule_stats={"molecule_count": 1},
    )
    save_extract_branch(tmp_path, extracted)
    persist_source_evidence(tmp_path, join_evidence_artifacts(extracted))


def test_extract_artifact_carries_regions_and_molecules_then_joins(
    tmp_path: Path,
) -> None:
    _archive_crop(tmp_path)
    extracted_input = _extracted()
    extracted_input.pages[0].ocr_backend = None
    extracted = _build(
        tmp_path,
        extracted=extracted_input,
        results=[_result()],
        molecule_stats={"molecule_count": 1},
    )

    extract_path = save_extract_branch(tmp_path, extracted)
    assert extract_path.name == "extract.json"
    assert extract_path.parent == tmp_path / "storage" / DOC / ".staging"
    assert load_extract_branch(tmp_path, DOC, "run-1") == extracted

    payload = json.loads(extract_path.read_text(encoding="utf-8"))
    assert "schema_version" not in payload
    assert "evidence_id" not in json.dumps(payload)
    assert payload["pages"][0]["text"] == "hello world"
    assert payload["pages"][0]["text_spans"][0]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    molecule = payload["pages"][0]["molecules"][0]
    assert molecule["page_idx"] == 0
    assert molecule["mol_img_path"] == f"storage/{DOC}/crops/a.png"
    assert payload["meta"]["molecule_stats"]["molecule_count"] == 1

    joined = join_evidence_artifacts(extracted)
    assert isinstance(joined, DocumentEvidenceArtifact)
    # Ordered top-to-bottom by ``_evidence_sort_key``: the molecule sits highest
    # on the page, the figure next, the text span lowest.
    assert [item.kind for item in joined.evidence] == [
        "molecule",
        "image_region",
        "text_span",
    ]
    molecule_evidence = next(
        item for item in joined.evidence if item.kind == "molecule"
    )
    assert json.loads(molecule_evidence.raw_text) == {
        "esmiles": "CCO<sep>",
        "moldet_conf": 0.95,
        "name": "EtOH",
        "smiles": "CCO",
    }
    assert joined.evidence_ids == [item.evidence_id for item in joined.evidence]
    persist_source_evidence(tmp_path, joined)
    assert not (extract_path.parent.parent.parent / "bbox.json").exists()


def test_join_registers_table_span(tmp_path: Path) -> None:
    extracted_input = _extracted()
    extracted_input.pages[0].text_spans = [
        TextSpan("A | B", (10.0, 10.0, 30.0, 30.0), 2)
    ]

    joined = join_evidence_artifacts(_build(tmp_path, extracted=extracted_input))

    assert [item.kind for item in joined.evidence] == ["image_region", "table_span"]


def test_join_prefers_molecule_bbox_over_overlapping_image_region(
    tmp_path: Path,
) -> None:
    """Join-time bbox dedup keeps MolDet molecule evidence over figure evidence."""
    _archive_crop(tmp_path)
    candidate = _candidate()
    candidate.detections[0] = replace(
        candidate.detections[0], bbox=(10.0, 20.0, 30.0, 40.0)
    )

    joined = join_evidence_artifacts(_build(tmp_path, results=[_result(candidate)]))

    assert [item.kind for item in joined.evidence].count("molecule") == 1
    assert not any(item.kind == "image_region" for item in joined.evidence)
    assert any(item.kind == "text_span" for item in joined.evidence)


def test_join_keeps_one_row_per_location(tmp_path: Path) -> None:
    """A location *is* the evidence ID, so two kinds on one bbox collapse to one.

    The stronger claim keeps its ``kind``; the loser's content is folded in rather
    than dropped.
    """
    _archive_crop(tmp_path)
    candidate = _candidate()
    candidate.detections[0] = replace(
        candidate.detections[0],
        bbox=(1.0, 2.0, 3.0, 4.0),  # the text span's rect
    )

    joined = join_evidence_artifacts(_build(tmp_path, results=[_result(candidate)]))

    locations = [(item.page, item.bbox) for item in joined.evidence]
    assert len(locations) == len(set(locations)), "one row per location"
    assert not any(item.kind == "text_span" for item in joined.evidence)
    molecule = next(item for item in joined.evidence if item.kind == "molecule")
    assert molecule.raw_text, "the winner keeps content"


def test_join_keeps_the_content_bearing_molecule_over_an_overlapping_bare_one(
    tmp_path: Path,
) -> None:
    """An overlapping claim without content never displaces one that has it.

    A cross-model layout region re-typed to a molecule carries MolDet's own
    geometry but no payload, and its box never matches the molecule pass' exactly
    (different render DPI).  Letting it win would drop the SMILES and the crop.
    """
    _archive_crop(tmp_path)
    extracted_input = _layout_extracted()
    # R3: the ``chem`` figure region becomes the molecule MolDet found in it,
    # with the slightly larger box the layout render produces.
    extracted_input.pages[0].regions[1].update(
        {"kind": "molecule", "type": "molecule", "bbox": [9.5, 19.5, 30.5, 40.5]}
    )
    candidate = _candidate()
    candidate.detections[0] = replace(
        candidate.detections[0], bbox=(10.0, 20.0, 30.0, 40.0)
    )

    joined = join_evidence_artifacts(
        _build(tmp_path, extracted=extracted_input, results=[_result(candidate)])
    )

    molecules = [item for item in joined.evidence if item.kind == "molecule"]
    assert len(molecules) == 1
    assert molecules[0].raw_text, "the content-bearing molecule keeps its payload"
    assert molecules[0].bbox == (10.0, 20.0, 30.0, 40.0)
    assert molecules[0].coref == f"storage/{DOC}/crops/a.png"


def test_join_records_every_figure_region_against_the_source_pdf(
    tmp_path: Path,
) -> None:
    """Figure regions survive as layout rectangles without any image file."""
    extracted_input = _extracted()
    page = extracted_input.pages[0]
    page.figure_bboxes = [(10.0, 20.0, 30.0, 40.0), (10.0, 60.0, 30.0, 80.0)]

    joined = join_evidence_artifacts(_build(tmp_path, extracted=extracted_input))

    assert {
        item.bbox: item.coref for item in joined.evidence if item.kind == "image_region"
    } == {
        (10.0, 20.0, 30.0, 40.0): f"storage/{DOC}/source.pdf",
        (10.0, 60.0, 30.0, 80.0): f"storage/{DOC}/source.pdf",
    }


def test_molecule_round_trip_preserves_markush_layer_fields(tmp_path: Path) -> None:
    """SQL-backed artifact reload keeps Layer 1 and Markush metadata distinct."""
    _archive_crop(tmp_path)
    candidate = _candidate()
    candidate.esmiles = "CCO<sep>R1-definition"
    candidate.properties = {"markush": True, "groups": "R1=alkyl"}
    extracted = _build(tmp_path, results=[_result(candidate)])
    save_extract_branch(tmp_path, extracted)
    persist_source_evidence(tmp_path, join_evidence_artifacts(extracted))

    restored, _ = load_detections(tmp_path, DOC)

    assert len(restored) == 1
    assert restored[0].canonical_smiles == "CCO"
    assert restored[0].esmiles == "CCO<sep>R1-definition"
    assert restored[0].properties["markush"] is True
    assert restored[0].properties["groups"] == "R1=alkyl"


def test_join_rejects_molecule_without_page_or_bbox(tmp_path: Path) -> None:
    extracted = _build(tmp_path)
    extracted.pages[0].molecules = [{"bbox_pdf": [1, 2, 3, 4]}]

    with pytest.raises(ValueError, match="page_idx and bbox_pdf"):
        join_evidence_artifacts(extracted)


def test_join_keeps_ocr_pdf_bbox_coordinates() -> None:
    extracted = ExtractedDocument(
        raw_text="hello",
        page_count=1,
        pages=[
            PageContent(
                page_num=1,
                text="hello",
                text_spans=[TextSpan("hello", (10.0, 8.0, 33.0, 23.0), 0)],
            )
        ],
    )
    rotated = [PageFrame(page=1, width=200.0, height=100.0, rotation=90)]
    artifact = build_extract_artifact(DOC, "run-1", extracted, rotated)
    joined = join_evidence_artifacts(artifact)
    assert joined.evidence[0].bbox == (10.0, 8.0, 33.0, 23.0)


def test_source_evidence_rejects_page_only_evidence() -> None:
    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.create(
            doc_id=DOC,
            page=1,
            bbox=None,  # type: ignore[arg-type]
            raw_text="legacy",
        )


def test_build_extract_artifact_requires_archived_molecule_crop(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="not archived"):
        _build(tmp_path, results=[_result()])


def test_join_order_is_independent_of_input_order(tmp_path: Path) -> None:
    _archive_crop(tmp_path)
    extracted = _build(
        tmp_path,
        results=[_result()],
        molecule_stats={"molecule_count": 1},
    )
    reversed_extract = extracted.model_copy(
        update={
            "pages": [
                extracted.pages[0].model_copy(
                    update={
                        "text_spans": list(reversed(extracted.pages[0].text_spans)),
                        "molecules": list(reversed(extracted.pages[0].molecules)),
                    }
                )
            ]
        }
    )
    assert (
        join_evidence_artifacts(extracted).model_dump()
        == join_evidence_artifacts(reversed_extract).model_dump()
    )


def _layout_extracted() -> ExtractedDocument:
    """An Extract branch authored by the local layout producer."""
    from mbforge.application.pipeline.layout.labels import kind_vocab

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
        # a second time by the join.
        text_spans=[TextSpan("Compound 1", text_bbox, 0)],
        figure_bboxes=[chem_bbox],
    )
    return ExtractedDocument(
        raw_text="Compound 1",
        page_count=1,
        parser="layout",
        pages=[page],
        ocr_stats={},
        kind_vocab=kind_vocab(),
    )


def test_join_mints_layout_regions_under_the_detector_kind(tmp_path: Path) -> None:
    """Typed regions become evidence under their own label, exactly once."""
    joined = join_evidence_artifacts(_build(tmp_path, extracted=_layout_extracted()))

    assert {item.kind: item.bbox for item in joined.evidence} == {
        "text": (1.0, 2.0, 3.0, 4.0),
        "chem": (10.0, 20.0, 30.0, 40.0),
    }
    # A region with no recognized text still needs a legal content reference.
    chem = next(item for item in joined.evidence if item.kind == "chem")
    assert chem.raw_text == ""
    assert chem.coref == f"storage/{DOC}/source.pdf"


def test_join_orders_layout_regions_by_reading_order(tmp_path: Path) -> None:
    """Column order beats the raster order for layout-authored evidence."""
    extracted_input = _layout_extracted()
    left = (10.0, 5.0, 40.0, 15.0)  # left column — later in raster order
    right = (50.0, 10.0, 90.0, 20.0)  # right column — earlier in raster order
    extracted_input.pages[0].regions = [
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
    extracted_input.pages[0].text_spans = []
    extracted_input.pages[0].figure_bboxes = []

    joined = join_evidence_artifacts(_build(tmp_path, extracted=extracted_input))

    assert [item.bbox for item in joined.evidence] == [left, right]


def test_load_extracted_reads_joined_pages(tmp_path: Path) -> None:
    _archive_crop(tmp_path)
    _publish_joined_evidence(tmp_path)

    restored = load_extracted(tmp_path, DOC)

    assert restored is not None
    assert restored.parser == "pymupdf"
    assert restored.page_count == 1
    assert restored.pages[0].page_num == 1
    assert restored.pages[0].text == "hello"
    assert restored.pages[0].text_spans[0].text == "hello"


def test_load_document_evidence_reads_sql_only(tmp_path: Path) -> None:
    evidence = SourceEvidence.create(
        doc_id=DOC,
        page=1,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text="canonical",
    )
    artifact = DocumentEvidenceArtifact(
        doc_id=DOC,
        run_id="run-1",
        conventions={"origin": "bottom-left"},
        pages=[PageFrame(page=1, width=10.0, height=10.0)],
        evidence=[evidence],
    )
    persist_source_evidence(tmp_path, artifact)

    assert [item.raw_text for item in load_document_evidence(tmp_path, DOC)] == [
        "canonical"
    ]


def test_corrupt_artifact_returns_none(tmp_path: Path) -> None:
    artifact = tmp_path / "storage" / DOC / "artifacts" / "pages.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{not json", encoding="utf-8")

    assert load_extracted(tmp_path, DOC) is None


def test_hydrate_context_fills_missing_fields(tmp_path: Path) -> None:
    _archive_crop(tmp_path)
    _publish_joined_evidence(tmp_path)
    document_md = tmp_path / "storage" / DOC / "document.md"
    document_md.write_text("# T\n", encoding="utf-8")

    ctx = PipelineContext(
        pdf_path=tmp_path / "x.pdf", library_root=tmp_path, doc_id=DOC, run_id="run-1"
    )
    hydrate_context_from_artifacts(ctx)

    assert ctx.extracted is not None
    assert ctx.extracted.page_count == 1
    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].properties.get("ocr_labels") == ["4A"]
    assert ctx.molecule_stats["molecule_count"] == 1
    assert ctx.document_md_path == document_md


def test_hydrate_context_does_not_override_fresh_state(tmp_path: Path) -> None:
    _archive_crop(tmp_path)
    _publish_joined_evidence(tmp_path)

    ctx = PipelineContext(
        pdf_path=tmp_path / "x.pdf",
        library_root=tmp_path,
        doc_id=DOC,
        run_id="run-1",
    )
    ctx.extracted = replace(_extracted(), page_count=99)
    hydrate_context_from_artifacts(ctx)

    assert ctx.extracted is not None
    assert ctx.extracted.page_count == 99


def test_publish_run_without_artifacts_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        publish_run(tmp_path, DOC, "run-1")

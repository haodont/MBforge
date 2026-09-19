"""Tests for raw branch artifacts and SQL source evidence."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from mbforge.core.evidence import SourceEvidence
from mbforge.core.molecule import Molecule
from mbforge.core.types import DetectionSource, ExtractionResult
from mbforge.pipeline.artifacts import (
    build_detection_artifact,
    build_extract_artifact,
    hydrate_context_from_artifacts,
    join_evidence_artifacts,
    load_detection_branch,
    load_detections,
    load_document_evidence,
    load_extract_branch,
    load_extracted,
    save_detection_branch,
    save_extract_branch,
)
from mbforge.pipeline.artifacts.evidence_models import (
    DocumentEvidenceArtifact,
    PageFrame,
)
from mbforge.pipeline.artifacts.staging import publish_run
from mbforge.pipeline.extract.text import ExtractedDocument, PageContent, TextSpan
from mbforge.pipeline.run.context import PipelineContext
from mbforge.storage.source_evidence import persist_source_evidence

DOC = "doc-artifacts"


def _extracted() -> ExtractedDocument:
    page = PageContent(
        page_num=1,
        text="hello world",
        ocr_dpi=200,
        text_spans=[TextSpan("hello", (1.0, 2.0, 3.0, 4.0), 0)],
        figure_bboxes=[(10.0, 20.0, 30.0, 40.0)],
        ocr_backend="paddleocr",
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


def _archive_crop(tmp_path: Path) -> None:
    crop = tmp_path / "storage" / DOC / "crops" / "a.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"png")


def _publish_joined_evidence(tmp_path: Path, run_id: str = "run-1") -> None:
    extracted = build_extract_artifact(DOC, run_id, _extracted(), _frames())
    detection = build_detection_artifact(
        DOC,
        run_id,
        [_result()],
        {"molecule_count": 1},
        _frames(),
        library_root=tmp_path,
    )
    save_extract_branch(tmp_path, extracted)
    save_detection_branch(tmp_path, detection)
    joined = join_evidence_artifacts(extracted, detection)
    persist_source_evidence(tmp_path, joined)


def test_v2_producers_write_independent_minimal_branches_and_join(
    tmp_path: Path,
) -> None:
    _archive_crop(tmp_path)
    frames = _frames()
    extracted_input = _extracted()
    extracted_input.pages[0].ocr_backend = None
    extracted = build_extract_artifact(DOC, "run-1", extracted_input, frames)
    detection = build_detection_artifact(
        DOC,
        "run-1",
        [_result()],
        {"molecule_count": 1},
        frames,
        library_root=tmp_path,
    )

    extract_path = save_extract_branch(tmp_path, extracted)
    detection_path = save_detection_branch(tmp_path, detection)
    assert extract_path.name == "extract.json"
    assert detection_path.name == "detection.json"
    assert extract_path.parent == detection_path.parent
    assert extract_path.parent == tmp_path / "storage" / DOC / ".staging"
    assert load_extract_branch(tmp_path, DOC, "run-1") == extracted
    assert load_detection_branch(tmp_path, DOC, "run-1") == detection

    extract_payload = json.loads(extract_path.read_text(encoding="utf-8"))
    assert "schema_version" not in extract_payload
    assert "evidence_id" not in json.dumps(extract_payload)
    assert extract_payload["pages"][0]["text"] == "hello world"
    assert extract_payload["pages"][0]["text_spans"][0]["bbox"] == [
        1.0,
        2.0,
        3.0,
        4.0,
    ]

    detection_payload = json.loads(detection_path.read_text(encoding="utf-8"))
    assert "schema_version" not in detection_payload
    assert "evidence_id" not in json.dumps(detection_payload)
    assert detection_payload["pages"][0]["detections"][0]["page_idx"] == 0

    joined = join_evidence_artifacts(extracted, detection)
    assert isinstance(joined, DocumentEvidenceArtifact)
    # Ordered top-to-bottom by ``_evidence_sort_key``: the molecule sits highest
    # on the page, the figure next, the text span lowest.
    assert [item.kind for item in joined.evidence] == [
        "molecule",
        "image_region",
        "text_span",
    ]
    molecule = next(item for item in joined.evidence if item.kind == "molecule")
    assert json.loads(molecule.raw_text) == {
        "esmiles": "CCO<sep>",
        "moldet_conf": 0.95,
        "name": "EtOH",
        "smiles": "CCO",
    }
    assert joined.evidence_ids == [item.evidence_id for item in joined.evidence]
    persist_source_evidence(tmp_path, joined)
    assert not (extract_path.parent.parent.parent / "bbox.json").exists()


def test_v2_join_registers_table_span(tmp_path: Path) -> None:
    extracted_input = _extracted()
    extracted_input.pages[0].text_spans = [
        TextSpan("A | B", (10.0, 10.0, 30.0, 30.0), 2)
    ]
    extracted = build_extract_artifact(DOC, "run-1", extracted_input, _frames())
    detection = build_detection_artifact(
        DOC, "run-1", [], {}, _frames(), library_root=tmp_path
    )

    joined = join_evidence_artifacts(extracted, detection)

    assert [item.kind for item in joined.evidence] == ["image_region", "table_span"]


def test_v2_join_prefers_molecule_bbox_over_overlapping_image_region(
    tmp_path: Path,
) -> None:
    """Join-time bbox dedup keeps MolDet molecule evidence over figure evidence."""
    _archive_crop(tmp_path)
    frames = _frames()
    extracted = build_extract_artifact(DOC, "run-1", _extracted(), frames)
    candidate = _candidate()
    candidate.detections[0] = replace(
        candidate.detections[0], bbox=(10.0, 20.0, 30.0, 40.0)
    )
    detection = build_detection_artifact(
        DOC,
        "run-1",
        [_result(candidate)],
        {},
        frames,
        library_root=tmp_path,
    )

    joined = join_evidence_artifacts(extracted, detection)

    assert [item.kind for item in joined.evidence].count("molecule") == 1
    assert not any(item.kind == "image_region" for item in joined.evidence)
    assert any(item.kind == "text_span" for item in joined.evidence)


def test_join_keeps_one_row_per_location(tmp_path: Path) -> None:
    """A location *is* the evidence ID, so two kinds on one bbox collapse to one.

    The stronger claim keeps its ``kind``; the loser's content is folded in rather
    than dropped.
    """
    _archive_crop(tmp_path)
    frames = _frames()
    extracted = build_extract_artifact(DOC, "run-1", _extracted(), frames)
    candidate = _candidate()
    candidate.detections[0] = replace(
        candidate.detections[0], bbox=(1.0, 2.0, 3.0, 4.0)  # the text span's rect
    )
    detection = build_detection_artifact(
        DOC, "run-1", [_result(candidate)], {}, frames, library_root=tmp_path
    )

    joined = join_evidence_artifacts(extracted, detection)

    locations = [(item.page, item.bbox) for item in joined.evidence]
    assert len(locations) == len(set(locations)), "one row per location"
    assert not any(item.kind == "text_span" for item in joined.evidence)
    molecule = next(item for item in joined.evidence if item.kind == "molecule")
    assert molecule.raw_text, "the winner keeps content"


def test_v2_join_records_every_figure_region_against_the_source_pdf(
    tmp_path: Path,
) -> None:
    """Figure regions survive as layout rectangles without any image file."""
    extracted_input = _extracted()
    page = extracted_input.pages[0]
    page.figure_bboxes = [(10.0, 20.0, 30.0, 40.0), (10.0, 60.0, 30.0, 80.0)]
    extracted = build_extract_artifact(DOC, "run-1", extracted_input, _frames())
    detection = build_detection_artifact(
        DOC, "run-1", [], {}, _frames(), library_root=tmp_path
    )

    joined = join_evidence_artifacts(extracted, detection)

    assert {
        item.bbox: item.coref for item in joined.evidence if item.kind == "image_region"
    } == {
        (10.0, 20.0, 30.0, 40.0): f"storage/{DOC}/source.pdf",
        (10.0, 60.0, 30.0, 80.0): f"storage/{DOC}/source.pdf",
    }


def test_v2_detection_round_trip_preserves_markush_layer_fields(tmp_path: Path) -> None:
    """SQL-backed artifact reload keeps Layer 1 and Markush metadata distinct."""
    _archive_crop(tmp_path)
    candidate = _candidate()
    candidate.esmiles = "CCO<sep>R1-definition"
    candidate.properties = {"markush": True, "groups": "R1=alkyl"}
    detection = build_detection_artifact(
        DOC,
        "run-1",
        [_result(candidate)],
        {},
        _frames(),
        library_root=tmp_path,
    )
    extracted = build_extract_artifact(DOC, "run-1", _extracted(), _frames())
    save_extract_branch(tmp_path, extracted)
    save_detection_branch(tmp_path, detection)
    joined = join_evidence_artifacts(extracted, detection)
    persist_source_evidence(tmp_path, joined)

    restored, _ = load_detections(tmp_path, DOC)

    assert len(restored) == 1
    assert restored[0].canonical_smiles == "CCO"
    assert restored[0].esmiles == "CCO<sep>R1-definition"
    assert restored[0].properties["markush"] is True
    assert restored[0].properties["groups"] == "R1=alkyl"


def test_v2_join_rejects_mismatched_run_and_missing_candidate_evidence(
    tmp_path: Path,
) -> None:
    _archive_crop(tmp_path)
    frames = _frames()
    extracted = build_extract_artifact(DOC, "run-1", _extracted(), frames)
    detection = build_detection_artifact(
        DOC,
        "run-2",
        [_result()],
        {},
        frames,
        library_root=tmp_path,
    )
    with pytest.raises(ValueError, match="run_id"):
        join_evidence_artifacts(extracted, detection)

    detection.run_id = "run-1"
    detection.pages[0].detections = [{"bbox_pdf": [1, 2, 3, 4]}]
    with pytest.raises(ValueError, match="page_idx and bbox_pdf"):
        join_evidence_artifacts(extracted, detection)


def test_v2_join_keeps_ocr_pdf_bbox_coordinates() -> None:
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
    artifact = build_extract_artifact(
        DOC,
        "run-1",
        extracted,
        [PageFrame(page=1, width=200.0, height=100.0, rotation=90)],
    )
    detection = build_detection_artifact(
        DOC,
        "run-1",
        [],
        {},
        [PageFrame(page=1, width=200.0, height=100.0, rotation=90)],
        library_root=".",
    )
    joined = join_evidence_artifacts(artifact, detection)
    assert joined.evidence[0].bbox == (10.0, 8.0, 33.0, 23.0)


def test_source_evidence_rejects_page_only_evidence() -> None:
    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.create(
            doc_id=DOC,
            page=1,
            bbox=None,  # type: ignore[arg-type]
            raw_text="legacy",
        )


def test_v2_detection_requires_archived_molecule_crop(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not archived"):
        build_detection_artifact(
            DOC,
            "run-1",
            [_result()],
            {},
            _frames(),
            library_root=tmp_path,
        )


def test_v2_join_order_is_independent_of_branch_input_order(tmp_path: Path) -> None:
    _archive_crop(tmp_path)
    frames = _frames()
    extracted = build_extract_artifact(DOC, "run-1", _extracted(), frames)
    candidate = _candidate()
    detection = build_detection_artifact(
        DOC,
        "run-1",
        [_result(candidate)],
        {"molecule_count": 1},
        frames,
        library_root=tmp_path,
    )
    reversed_extract = extracted.model_copy(
        update={
            "pages": [
                extracted.pages[0].model_copy(
                    update={"text_spans": list(reversed(extracted.pages[0].text_spans))}
                )
            ]
        }
    )
    reversed_detection = detection.model_copy(
        update={
            "pages": [
                detection.pages[0].model_copy(
                    update={"detections": list(reversed(detection.pages[0].detections))}
                )
            ]
        }
    )
    assert (
        join_evidence_artifacts(extracted, detection).model_dump()
        == join_evidence_artifacts(reversed_extract, reversed_detection).model_dump()
    )


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

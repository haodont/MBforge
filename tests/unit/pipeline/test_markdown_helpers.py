from __future__ import annotations

from pathlib import Path

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource
from mbforge.service.pipeline.artifacts.evidence_models import PageFrame
from mbforge.service.pipeline.markdown.esmiles_insert import insert_esmiles_blocks


def _source(
    doc_id: str,
    *,
    page: int,
    bbox: tuple[float, float, float, float],
    kind: str,
    raw_text: str = "",
) -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=bbox,
        kind=kind,
        raw_text=raw_text,
    )


def test_markdown_assembles_evidence_by_geometry_and_writes_map(
    tmp_path: Path,
) -> None:
    text_evidence = _source(
        "doc",
        page=1,
        bbox=(10.0, 160.0, 100.0, 170.0),
        kind="text",
        raw_text="Paragraph text.",
    )
    image_evidence = _source(
        "doc",
        page=1,
        bbox=(10.0, 120.0, 80.0, 150.0),
        kind="figcx",
        raw_text="storage/doc/images/figure.png",
    )
    molecule_evidence = _source(
        "doc",
        page=1,
        bbox=(10.0, 80.0, 40.0, 100.0),
        kind="molecule",
        raw_text="storage/doc/crops/mol.png",
    )
    candidate = Molecule(
        canonical_smiles="CCO",
        esmiles="CCO",
        detections=[
            DetectionSource(source="image", evidence_id=molecule_evidence.evidence_id)
        ],
        properties={"candidate_id": "candidate-1", "refs": ["4A"]},
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(
        [text_evidence, image_evidence, molecule_evidence],
        str(output_path),
        candidates=[candidate],
        pages=[PageFrame(page=1, width=200.0, height=200.0)],
        doc_id="doc",
    )

    content = output_path.read_text(encoding="utf-8")
    assert content.index("Paragraph text.") < content.index("image evidence=")
    assert content.index("image evidence=") < content.index("```esmiles")
    assert "%% candidate=candidate-1" in content
    assert "%% label=4A" in content

    assert not (tmp_path / "document.map.json").exists()


def test_markdown_tie_breaks_images_before_molecules_and_filters_candidates(
    tmp_path: Path,
) -> None:
    image_evidence = _source(
        "doc",
        page=1,
        bbox=(20.0, 100.0, 40.0, 120.0),
        kind="figcx",
        raw_text="storage/doc/images/figure.png",
    )
    molecule_evidence = _source(
        "doc",
        page=1,
        bbox=(20.0, 100.0, 40.0, 120.0),
        kind="molecule",
        raw_text="storage/doc/crops/mol.png",
    )
    rejected_evidence = _source(
        "doc",
        page=1,
        bbox=(20.0, 60.0, 40.0, 80.0),
        kind="molecule",
        raw_text="storage/doc/crops/rejected.png",
    )
    empty_evidence = _source(
        "doc",
        page=1,
        bbox=(20.0, 40.0, 40.0, 50.0),
        kind="molecule",
        raw_text="storage/doc/crops/empty.png",
    )
    accepted = Molecule(
        canonical_smiles="CCO",
        esmiles="CCO",
        detections=[
            DetectionSource(source="image", evidence_id=molecule_evidence.evidence_id)
        ],
        properties={"candidate_id": "accepted"},
    )
    rejected = Molecule(
        canonical_smiles="CCC",
        esmiles="CCC",
        status="rejected",
        detections=[
            DetectionSource(source="image", evidence_id=rejected_evidence.evidence_id)
        ],
        properties={"candidate_id": "rejected"},
    )
    empty = Molecule(
        canonical_smiles="",
        esmiles="",
        detections=[
            DetectionSource(source="image", evidence_id=empty_evidence.evidence_id)
        ],
        properties={"candidate_id": "empty"},
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(
        [image_evidence, molecule_evidence, rejected_evidence, empty_evidence],
        str(output_path),
        candidates=[accepted, rejected, empty],
        pages=[PageFrame(page=1, width=200.0, height=200.0)],
        doc_id="doc",
    )

    content = output_path.read_text(encoding="utf-8")
    assert content.index("image evidence=") < content.index("```esmiles")
    assert "%% candidate=accepted" in content
    assert "%% candidate=rejected" not in content
    assert "%% candidate=empty" not in content


def test_markdown_renders_candidate_on_page_without_text(tmp_path: Path) -> None:
    molecule_evidence = _source(
        "doc",
        page=2,
        bbox=(10.0, 20.0, 40.0, 50.0),
        kind="molecule",
        raw_text="storage/doc/crops/mol.png",
    )
    candidate = Molecule(
        canonical_smiles="CCN",
        esmiles="CCN",
        detections=[
            DetectionSource(source="image", evidence_id=molecule_evidence.evidence_id)
        ],
        properties={"candidate_id": "candidate-2"},
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(
        [molecule_evidence],
        str(output_path),
        candidates=[candidate],
        pages=[PageFrame(page=2, width=200.0, height=200.0)],
        doc_id="doc",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "<!-- PAGE 2 -->" in content
    assert "%% candidate=candidate-2" in content
    assert "CCN" in content

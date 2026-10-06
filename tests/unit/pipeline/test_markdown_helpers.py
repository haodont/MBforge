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


def test_markdown_emits_numbered_paragraph_once_on_its_starting_page(
    tmp_path: Path,
) -> None:
    """A patent paragraph split by a page break is one block, not two.

    The layout cut ``[0003]`` at the foot of page 1 and carried the rest onto
    page 2; the marker is the paragraph's real boundary, so the continuation
    belongs to the block that already started rather than to a block of its own.
    """
    opening = _source(
        "doc",
        page=1,
        bbox=(10.0, 700.0, 100.0, 720.0),
        kind="text",
        raw_text="[0003] MRGX2 is Gq-coupled … cultured mast cells (D.",
    )
    continuation = _source(
        "doc",
        page=2,
        bbox=(10.0, 800.0, 100.0, 810.0),
        kind="text",
        raw_text="Fujisawa et al., J Allergy Clin Immunol …).",
    )
    following = _source(
        "doc",
        page=2,
        bbox=(10.0, 600.0, 100.0, 610.0),
        kind="text",
        raw_text="[0004] MRGX2 is potentially involved in host defense.",
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(
        [opening, continuation, following],
        str(output_path),
        pages=[
            PageFrame(page=1, width=200.0, height=900.0),
            PageFrame(page=2, width=200.0, height=900.0),
        ],
        doc_id="doc",
    )

    content = output_path.read_text(encoding="utf-8")
    assert content.count("[0003]") == 1
    assert content.count("Fujisawa") == 1
    paragraph = next(line for line in content.splitlines() if line.startswith("[0003]"))
    assert paragraph.endswith("(D. Fujisawa et al., J Allergy Clin Immunol …).")
    # Rendered with the page its first fragment sits on, not the page it ends on.
    assert content.index("[0003]") < content.index("<!-- PAGE 2 -->")


def test_markdown_renders_indented_sub_items_as_a_nested_list(tmp_path: Path) -> None:
    """A paragraph's deeper-left-edge fragments keep their level in Markdown."""
    head = _source(
        "doc",
        page=1,
        bbox=(85.0, 700.0, 500.0, 720.0),
        kind="text",
        raw_text="[0006] One aspect of the invention provides a compound:",
    )
    first = _source(
        "doc",
        page=1,
        bbox=(125.0, 600.0, 500.0, 610.0),
        kind="text",
        raw_text="(a) C1-4 alkyl which is substituted",
    )
    second = _source(
        "doc",
        page=1,
        bbox=(125.0, 500.0, 500.0, 510.0),
        kind="text",
        raw_text="(b) a cyclic group selected from",
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(
        [head, first, second],
        str(output_path),
        pages=[PageFrame(page=1, width=600.0, height=900.0)],
        doc_id="doc",
    )

    content = output_path.read_text(encoding="utf-8")
    assert (
        "[0006] One aspect of the invention provides a compound:\n"
        "\n"
        "- (a) C1-4 alkyl which is substituted\n"
        "- (b) a cyclic group selected from\n"
    ) in content


def test_markdown_renders_a_centred_block_as_a_heading(tmp_path: Path) -> None:
    """The layout's centred block is the trustworthy heading signal."""
    body = [
        _source(
            "doc",
            page=1,
            bbox=(85.0, 700.0 - index * 10.0 - 10.0, 500.0, 700.0 - index * 10.0),
            kind="text",
            raw_text=f"Body line {index}",
        )
        for index in range(3)
    ]
    heading = _source(
        "doc",
        page=1,
        bbox=(227.0, 400.0, 369.0, 410.0),
        kind="sec",
        raw_text="FIELD OF THE INVENTION",
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(
        [*body, heading],
        str(output_path),
        pages=[PageFrame(page=1, width=600.0, height=900.0)],
        doc_id="doc",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "## FIELD OF THE INVENTION" in content
    assert "Body line 0" in content

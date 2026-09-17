from __future__ import annotations

from pathlib import Path

from mbforge.core.evidence import SourceEvidence
from mbforge.core.molecule import Molecule
from mbforge.pipeline.artifacts.evidence_models import (
    CandidateArtifact,
    DocumentEvidenceArtifact,
    PageFrame,
)
from mbforge.pipeline.detection.extraction import candidate_id
from mbforge.pipeline.markdown.esmiles_insert import insert_esmiles_blocks
from mbforge.pipeline.persist.text_links import (
    _find_esmiles_in_text,
    enrich_molecule_contexts_from_markdown,
)


def test_register_molecules_from_text_skips_non_complete_roles(tmp_path: Path) -> None:
    from mbforge.pipeline.persist.text_links import register_molecules_from_text
    from mbforge.storage.sqlite.database import DatabaseManager

    markdown = tmp_path / "document.md"
    markdown.write_text("# Doc", encoding="utf-8")
    fragment = Molecule(canonical_smiles="*C", esmiles="*C", name="R1")
    fragment.properties["structure_role"] = "fragment"
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()

    register_molecules_from_text(str(markdown), [fragment], "doc-1", str(tmp_path))

    assert (
        db.execute("SELECT COUNT(*) AS count FROM molecules", db="mol")[0]["count"] == 0
    )
    assert (
        db.execute("SELECT COUNT(*) AS count FROM text_molecule_links", db="mol")[0][
            "count"
        ]
        == 0
    )


def test_enrich_molecule_contexts_from_markdown(tmp_path: Path) -> None:
    molecule = Molecule(canonical_smiles="CCO", esmiles="CCO", name="")
    markdown = tmp_path / "document.md"
    markdown.write_text(
        "# Formula I\n\n"
        "Formula I compounds have R1/R2 substituents.\n\n"
        "```esmiles\nCCO\n```\n",
        encoding="utf-8",
    )
    enriched = enrich_molecule_contexts_from_markdown(str(markdown), [molecule])

    assert enriched == 1
    assert "Formula I" in molecule.properties["role_contexts"][0]


def test_enrich_attaches_distant_compound_context_for_review_routing(
    tmp_path: Path,
) -> None:
    from mbforge.pipeline.detection.structure_role import (
        classify_structure_role,
    )

    cid = candidate_id("doc", "CCO", 8, (1.0, 2.0, 3.0, 4.0))
    markdown = tmp_path / "document.md"
    markdown.write_text(
        "<!-- PAGE 8 -->\n"
        "```esmiles\n"
        f"%% page=8\n%% candidate={cid}\nCCO\n"
        "```\n"
        "\n<!-- PAGE 21 -->\n"
        "实施例4：化合物4是1S,3R(4A)和1R,3S(4B)的混合物。"
        "4A与4B为拆分产物，构型暂定。\n",
        encoding="utf-8",
    )
    molecule = Molecule(
        canonical_smiles="CCO",
        esmiles="CCO",
        name="4A",
        properties={"candidate_id": cid},
    )

    enriched = enrich_molecule_contexts_from_markdown(str(markdown), [molecule])

    assert enriched == 1
    assert any("拆分产物" in value for value in molecule.properties["role_contexts"])
    assert classify_structure_role(molecule) == "review_required"


def test_enrich_recovers_unique_nearby_compound_label_for_image_placeholder(
    tmp_path: Path,
) -> None:
    cid = candidate_id("doc", "CCO", 8, (1.0, 2.0, 3.0, 4.0))
    markdown = tmp_path / "document.md"
    markdown.write_text(
        "<!-- PAGE 8 -->\n"
        "实施例 28：制备目标化合物。\n"
        "```esmiles\n"
        f"%% page=8\n%% candidate={cid}\nCCO\n"
        "```\n",
        encoding="utf-8",
    )
    molecule = Molecule(
        canonical_smiles="CCO",
        esmiles="CCO",
        name="![](images/structure.jpg)",
        properties={"candidate_id": cid},
    )

    enriched = enrich_molecule_contexts_from_markdown(str(markdown), [molecule])

    assert enriched == 1
    assert molecule.properties["explicit_context_labels"] == ["28"]


def _source(
    doc_id: str,
    *,
    page: int,
    bbox: tuple[float, float, float, float],
    kind: str,
    raw_text: str = "",
    coref: str = "",
) -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=bbox,
        kind=kind,
        raw_text=raw_text,
        coref=coref,
    )


def test_markdown_assembles_evidence_by_geometry_and_writes_map(
    tmp_path: Path,
) -> None:
    text_evidence = _source(
        "doc",
        page=1,
        bbox=(10.0, 160.0, 100.0, 170.0),
        kind="text_span",
        raw_text="Paragraph text.",
    )
    image_evidence = _source(
        "doc",
        page=1,
        bbox=(10.0, 120.0, 80.0, 150.0),
        kind="image_region",
        coref="storage/doc/images/figure.png",
    )
    molecule_evidence = _source(
        "doc",
        page=1,
        bbox=(10.0, 80.0, 40.0, 100.0),
        kind="molecule",
        coref="storage/doc/crops/mol.png",
    )
    artifact = DocumentEvidenceArtifact(
        doc_id="doc",
        run_id="run-1",
        conventions={"origin": "bottom-left"},
        pages=[PageFrame(page=1, width=200.0, height=200.0)],
        evidence=[text_evidence, image_evidence, molecule_evidence],
        candidates=[
            CandidateArtifact(
                candidate_id="candidate-1",
                evidence_ids=[molecule_evidence.evidence_id],
                status="accepted",
                smiles="CCO",
                esmiles="CCO",
                refs=["4A"],
            )
        ],
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(artifact, str(output_path))

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
        kind="image_region",
        coref="storage/doc/images/figure.png",
    )
    molecule_evidence = _source(
        "doc",
        page=1,
        bbox=(20.0, 100.0, 40.0, 120.0),
        kind="molecule",
        coref="storage/doc/crops/mol.png",
    )
    rejected_evidence = _source(
        "doc",
        page=1,
        bbox=(20.0, 60.0, 40.0, 80.0),
        kind="molecule",
        coref="storage/doc/crops/rejected.png",
    )
    empty_evidence = _source(
        "doc",
        page=1,
        bbox=(20.0, 40.0, 40.0, 50.0),
        kind="molecule",
        coref="storage/doc/crops/empty.png",
    )
    artifact = DocumentEvidenceArtifact(
        doc_id="doc",
        run_id="run-1",
        conventions={"origin": "bottom-left"},
        pages=[PageFrame(page=1, width=200.0, height=200.0)],
        evidence=[
            image_evidence,
            molecule_evidence,
            rejected_evidence,
            empty_evidence,
        ],
        candidates=[
            CandidateArtifact(
                candidate_id="accepted",
                evidence_ids=[molecule_evidence.evidence_id],
                status="accepted",
                smiles="CCO",
                esmiles="CCO",
            ),
            CandidateArtifact(
                candidate_id="rejected",
                evidence_ids=[rejected_evidence.evidence_id],
                status="rejected",
                smiles="CCC",
                esmiles="CCC",
            ),
            CandidateArtifact(
                candidate_id="empty",
                evidence_ids=[empty_evidence.evidence_id],
                status="accepted",
                smiles="",
                esmiles="",
            ),
        ],
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(artifact, str(output_path))

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
        coref="storage/doc/crops/mol.png",
    )
    artifact = DocumentEvidenceArtifact(
        doc_id="doc",
        run_id="run-1",
        conventions={"origin": "bottom-left"},
        pages=[PageFrame(page=2, width=200.0, height=200.0)],
        evidence=[molecule_evidence],
        candidates=[
            CandidateArtifact(
                candidate_id="candidate-2",
                evidence_ids=[molecule_evidence.evidence_id],
                status="accepted",
                smiles="CCN",
                esmiles="CCN",
            )
        ],
    )
    output_path = tmp_path / "document.md"

    insert_esmiles_blocks(artifact, str(output_path))

    content = output_path.read_text(encoding="utf-8")
    assert "<!-- PAGE 2 -->" in content
    assert "%% candidate=candidate-2" in content
    assert "CCN" in content


def test_find_esmiles_in_text_prefers_candidate_id_over_shared_prefix() -> None:
    smiles_a = "CCOC(=O)c1ccccc1"
    smiles_b = "CCOC(=O)c1cccnc1"
    assert smiles_a[:12] == smiles_b[:12]
    id_b = candidate_id("", smiles_b, 2, (1.0, 2.0, 3.0, 4.0))
    text = (
        "## First\n\n"
        f"```esmiles\n%% page=1\n{smiles_a}\n```\n\n"
        "## Second\n\n"
        f"```esmiles\n%% page=2\n%% candidate={id_b}\n{smiles_b}\n```\n"
    )

    hit = _find_esmiles_in_text(text, smiles_b, candidate_id=id_b)

    assert hit is not None
    start, end, section = hit
    assert section == "Second"
    assert smiles_b in text[start:end]


def test_find_esmiles_in_text_matches_complete_structure() -> None:
    smiles_a = "CCOC(=O)c1ccccc1"
    smiles_b = "CCOC(=O)c1cccnc1"
    assert smiles_a[:12] == smiles_b[:12]
    text = (
        "## First\n\n"
        f"```esmiles\n{smiles_a}\n```\n\n"
        "## Second\n\n"
        f"```esmiles\n{smiles_b}\n```\n"
    )

    hit = _find_esmiles_in_text(text, smiles_b)

    assert hit is not None
    _, _, section = hit
    assert section == "Second"


def test_find_esmiles_in_text_prefix_does_not_cross_match() -> None:
    text = "```esmiles\nCCOC\n```\n"
    assert _find_esmiles_in_text(text, "CCO") is None


def test_enrich_molecule_contexts_matches_block_by_candidate_id(tmp_path: Path) -> None:
    smiles_a = "CCOC(=O)c1ccccc1"
    smiles_b = "CCOC(=O)c1cccnc1"
    id_b = candidate_id("", smiles_b, 2, (1.0, 2.0, 3.0, 4.0))
    markdown = tmp_path / "document.md"
    markdown.write_text(
        "## Benzoate section\n\n"
        f"```esmiles\n{smiles_a}\n```\n\n"
        "## Pyridine section\n\n"
        f"```esmiles\n%% candidate={id_b}\n{smiles_b}\n```\n",
        encoding="utf-8",
    )
    molecule = Molecule(canonical_smiles=smiles_b, esmiles=smiles_b, name="")
    molecule.properties["candidate_id"] = id_b

    enriched = enrich_molecule_contexts_from_markdown(str(markdown), [molecule])

    assert enriched == 1
    assert molecule.properties["role_contexts"][0].startswith("Pyridine section")

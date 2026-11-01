"""Usage tests for the SQL-backed PatentStage facts boundary.

Protects the whole deterministic (zero-token) pipeline in one place: entry
identity from titles and body prose, document-local example identity, assay
method extraction, synthesis routes, printed characterization data, printed
chemistry names, mass cross-checks, and the model's gap links — then the stage
itself: publish at the document root, evidence rebuild, persistence and
republish.

Functions under test: ``PatentStage.execute`` +
``extract_entries_from_title`` / ``extract_entries_from_body`` /
``extract_assay_method_from_title`` / ``extract_synthesis_routes`` /
``extract_characterization`` / ``extract_compound_names`` / ``find_mass_mismatches``
(``mbforge.service.pipeline.stages.patent_stage``), ``associate_facts`` /
``apply_gap_links`` (``mbforge.service.pipeline.patent.association``) and the
artifact store (``mbforge.service.use_cases.documents.patent_facts``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from mbforge.db.source_evidence import persist_source_evidence
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.activity import ActivityMeasurement, MeasurementValue
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource
from mbforge.service.pipeline.extract.text import ExtractedDocument, PageContent
from mbforge.service.pipeline.patent.association import (
    apply_gap_links,
    associate_facts,
)
from mbforge.service.pipeline.patent.sections import ParsedSection
from mbforge.service.pipeline.run.context import PipelineContext
from mbforge.service.pipeline.stages.patent_stage import (
    PatentStage,
    extract_assay_method_from_title,
    extract_characterization,
    extract_compound_names,
    extract_entries_from_body,
    extract_entries_from_title,
    extract_synthesis_routes,
    find_mass_mismatches,
)
from mbforge.service.use_cases.documents.patent_facts import (
    iter_published_doc_ids,
    load_patent_facts,
)


@dataclass
class FakePage:
    page_num: int
    text: str


def _make_ctx(tmp_path: Path, pages: list[FakePage]) -> PipelineContext:
    ctx = PipelineContext(
        pdf_path=tmp_path / "source.pdf",
        library_root=tmp_path,
        doc_id="doc1",
        run_id="run-1",
    )
    ctx.extracted = ExtractedDocument(
        raw_text="\n".join(p.text for p in pages),
        page_count=len(pages),
        pages=[PageContent(page_num=p.page_num, text=p.text) for p in pages],
    )
    return ctx


def _seed_evidence(tmp_path: Path, pages: list[FakePage]) -> list[SourceEvidence]:
    """Persist ordered text blocks as SQL source evidence for ``doc1``."""
    blocks: list[SourceEvidence] = []
    baseline_y = 1000.0
    for page in pages:
        y = baseline_y
        for line in page.text.splitlines():
            line = line.strip()
            if not line:
                continue
            blocks.append(
                SourceEvidence.create(
                    doc_id="doc1",
                    page=page.page_num,
                    bbox=(10.0, y, 200.0, y + 20.0),
                    raw_text=line,
                )
            )
            y -= 40.0
    persist_source_evidence(tmp_path, blocks)
    return blocks


@pytest.fixture(autouse=True)
def _activity_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control stage readings; the real parser has separate usage coverage."""
    monkeypatch.setattr(
        "mbforge.service.pipeline.activity.extraction.extract_activity_measurements_from_evidence",
        lambda _evidence, _doc_id: ([], []),
        raising=False,
    )


# ── entry extraction ────────────────────────────────────────────────


def test_entries_come_from_titles_and_body_prose() -> None:
    """Title designations and body prose both mint entries, deterministically.

    A title supplies the role and the bracketed codes as a name; body prose
    declares the compounds most patents never name; identifiers are stable
    across runs; a bioassay title declares no compound at all; a mass reading
    (``制得化合物36.8mg``) is a yield, not compound 36; and a section keeps only
    the blocks that name it.
    """
    titled = extract_entries_from_title(
        "实施例21：化合物23(IGP-20024-01)(A057-130)的制备", "d", "sec1", 21
    )
    assert len(titled) == 1
    entry = titled[0]
    assert entry["label_raw"] == "化合物23"
    assert entry["entry_role"] == "preparation"
    assert entry["name_raw"] == "IGP-20024-01 / A057-130"
    assert entry["section_id"] == "sec1"
    assert entry["evidence_ids"] == []

    multi = extract_entries_from_title("实施例13：化合物13和14的制备", "d", "sec1", 13)
    assert [e["label_raw"] for e in multi] == ["化合物13", "化合物14"]

    again = extract_entries_from_title("实施例1：化合物1的制备", "d", "s", 1)
    same = extract_entries_from_title("实施例1：化合物1的制备", "d", "s", 1)
    assert again[0]["entry_id"] == same[0]["entry_id"]

    body = extract_entries_from_body(
        [("ev-1", "参考实施例2，制得化合物7；化合物8为中间体。")],
        "d",
        "sec1",
        "example",
    )
    assert [e["label_raw"] for e in body] == ["化合物7", "化合物8"]
    assert [e["label_key"] for e in body] == ["7", "8"]
    assert all(e["evidence_ids"] == ["ev-1"] for e in body)
    assert all(e["section_id"] == "sec1" for e in body)
    assert all(e["entry_role"] == "example" for e in body)

    named = extract_entries_from_body(
        [
            ("ev-1", "化合物7的合成。"),
            ("ev-2", "该中间体经过滤。"),
            ("ev-3", "取化合物7测定。"),
        ],
        "d",
        "sec1",
        "preparation",
    )
    assert len(named) == 1
    assert named[0]["evidence_ids"] == ["ev-1", "ev-3"]
    assert named[0]["entry_role"] == "preparation"

    assert (
        extract_entries_from_title("实施例27：化合物对MRGPRX2的抑制活性", "d", "s", 27)
        == []
    )
    assert (
        extract_entries_from_body(
            [("ev-1", "参考实施例1的合成方法，制得化合物36.8mg，收率16.5%。")],
            "d",
            "sec1",
            "example",
        )
        == []
    )


# ── document-local example identity ─────────────────────────────────


def _example_section(section_id: str, heading: str) -> ParsedSection:
    return ParsedSection(
        section_id=section_id,
        title=heading,
        kind="example",
        page_start=1,
        page_end=1,
        raw_text=heading,
        labels=[],
        esmiles_candidate_ids=[],
        evidence_ids=[f"ev-{section_id}"],
        title_evidence_ids=[f"ev-{section_id}"],
        heading_line=heading,
    )


def _entry(entry_id: str, compound: str, section_id: str) -> dict:
    return {
        "entry_id": entry_id,
        "doc_id": "doc1",
        "label_raw": compound,
        "label_key": compound.removeprefix("化合物"),
        "entry_role": "example",
        "name_raw": "",
        "section_id": section_id,
        "entity_id": None,
        "structure_status": "missing",
        "extraction_status": "pending",
        "linking_status": "pending",
        "review_status": "pending",
        "evidence_ids": [f"ev-{section_id}"],
    }


def _example_measurement(reference: str, key: str) -> dict:
    return {
        "measurement_id": "m-1",
        "doc_id": "doc1",
        "metric": "IC50",
        "value": {},
        "evidence_ids": ["ev-table"],
        "provenance": {
            "reference_raw": reference,
            "reference_key": key,
            "reference_type": "example",
        },
    }


def test_an_example_reference_resolves_to_its_own_sections_compound() -> None:
    """``实施例2`` is the compound that section prepares, not compound 2.

    The reference resolves inside the section that prints it, a heading split
    across blocks still declares one compound without ambiguity, an example with
    no printed compound falls back to its section identity, a bare number never
    borrows a compound declared by another section — and a designation no section
    declares is declared from the passage itself, pending review.
    """
    sections = [
        _example_section("sec-2", "实施例2：化合物9的制备"),
        _example_section("sec-5", "实施例5：化合物2的制备"),
    ]
    entries = [
        _entry("entry-9", "化合物9", "sec-2"),
        _entry("entry-2", "化合物2", "sec-5"),
    ]
    measurement = _example_measurement("实施例2", "2")
    issues: list[dict] = []
    associate_facts(
        sections, entries, [], [measurement], [], {"ev-sec-2", "ev-table"}, issues
    )
    assert measurement["compound_entry_id"] == "entry-9"

    split_sections = [
        _example_section("sec-2-a", "实施例2：化合物9的制备"),
        _example_section("sec-2-b", "实施例2"),
    ]
    split_entries = [
        _entry("entry-9-a", "化合物9", "sec-2-a"),
        _entry("entry-9-b", "化合物9", "sec-2-b"),
    ]
    split_measurement = _example_measurement("实施例2", "2")
    split_issues: list[dict] = []
    associate_facts(
        split_sections,
        split_entries,
        [],
        [split_measurement],
        [],
        {"ev-sec-2-a", "ev-sec-2-b", "ev-table"},
        split_issues,
    )
    assert split_measurement["compound_entry_id"] == "entry-9-a"
    assert not any(
        issue["code"] == "compound_entry_ambiguous" for issue in split_issues
    )

    named_section = _example_section("sec-2", "实施例2：N-((1R,3S)-3-氨基环己基)甲酰胺")
    named_entry = {
        **_entry("entry-example-2", "化合物2", "sec-2"),
        "label_raw": "实施例2",
        "label_key": "@example:2",
    }
    named_measurement = _example_measurement("实施例2", "2")
    named_issues: list[dict] = []
    intermediate = {
        **_entry("entry-reagent-1", "化合物1", "sec-2"),
        "evidence_ids": ["ev-body-reagent"],
    }
    associate_facts(
        [named_section],
        [named_entry, intermediate],
        [],
        [named_measurement],
        [],
        {"ev-sec-2", "ev-table", "ev-body-reagent"},
        named_issues,
    )
    assert named_measurement["compound_entry_id"] == "entry-example-2"

    foreign_section = [_example_section("sec-5", "实施例5：化合物2的制备")]
    foreign_entries = [
        _entry("entry-2", "化合物2", "sec-5"),
        _entry("entry-3", "化合物3", "sec-5"),
    ]
    foreign_measurement = _example_measurement("实施例3", "3")
    foreign_issues: list[dict] = []
    associate_facts(
        foreign_section,
        foreign_entries,
        [],
        [foreign_measurement],
        [],
        {"ev-sec-5", "ev-table"},
        foreign_issues,
    )
    assert foreign_measurement["compound_entry_id"] != "entry-3"
    declared = next(
        entry
        for entry in foreign_entries
        if entry["entry_id"] == foreign_measurement["compound_entry_id"]
    )
    # A designation no section declares is declared from the passage that prints it,
    # pending review — never borrowed from the section that declares ``化合物3``.
    assert declared["label_key"] == "@example:3"
    assert declared["review_status"] == "pending"
    assert not any(
        issue["code"] == "compound_reference_unresolved" for issue in foreign_issues
    )


# ── assay method extraction ─────────────────────────────────────────


def test_an_assay_method_comes_from_the_title_only_when_it_names_one() -> None:
    """A title names the target and endpoint; an English heading names both too.

    A preparation title declares no assay at all, and a latin token sets the
    assay type case-insensitively.
    """
    chinese = extract_assay_method_from_title(
        "实施例27：化合物对MRGPRX2受体抑制活性", "d", "s27", 27, 29
    )
    repeated = extract_assay_method_from_title(
        "实施例27：化合物对MRGPRX2受体抑制活性", "d", "s27", 27, 29
    )
    assert chinese is not None and repeated is not None
    assert chinese["target"] == "MRGPRX2"
    assert chinese["endpoint"] == "抑制活性"
    assert chinese["assay_method_id"] == repeated["assay_method_id"]
    assert chinese["comparison_key"] is None
    assert chinese["section_id"] == "s27"
    assert chinese["doc_id"] == "d"
    assert chinese["page_start"] == 27
    assert chinese["page_end"] == 29
    assert chinese["evidence_ids"] == []

    english = extract_assay_method_from_title(
        "Example A:MRGPRX2 FLIPR Calcium Mobilization Assay", "d", "secA", 60, 61
    )
    assert english is not None
    assert english["target"] == "MRGPRX2"
    assert english["endpoint"] == "测定"

    assert (
        extract_assay_method_from_title("实施例1：化合物1的制备", "d", "s", 1, 1)
        is None
    )

    upper = extract_assay_method_from_title(
        "实施例5：化合物对MRGPRX2受体(IC50)抑制活性", "d", "s5", 5, 5
    )
    assert upper is not None and upper["assay_type"] == "IC50"
    lower = extract_assay_method_from_title(
        "实施例6：化合物对受体抑制活性(ic50)", "d", "s6", 6, 6
    )
    assert lower is not None and lower["assay_type"] == "ic50"


# ── synthesis routes (deterministic, zero-token) ────────────────────
#
# Forms and their rejected neighbours come from the corpus catalog
# (docs/wiki/patent-extraction-forms.md §2/§5): the route is body prose, the
# documents print no 合成路线 heading, and a quantity after a designation is a
# mass, not a compound number.


def _route_input(
    kind: str, heading: str, lines: list[str]
) -> tuple[ParsedSection, dict[str, SourceEvidence]]:
    blocks: dict[str, SourceEvidence] = {}
    evidence_ids: list[str] = []
    for index, line in enumerate(lines):
        item = SourceEvidence.create(
            doc_id="doc1",
            page=143,
            bbox=(10.0, 900.0 - index * 30.0, 200.0, 920.0 - index * 30.0),
            raw_text=line,
        )
        blocks[item.evidence_id] = item
        evidence_ids.append(item.evidence_id)
    section = ParsedSection(
        section_id="sec-1",
        title=heading,
        kind=kind,
        page_start=143,
        page_end=143,
        raw_text="\n".join(lines),
        labels=[],
        esmiles_candidate_ids=[],
        evidence_ids=evidence_ids,
        title_evidence_ids=[evidence_ids[0]],
        heading_line=heading,
    )
    return section, blocks


def test_synthesis_routes_keep_their_steps_and_refuse_non_routes() -> None:
    """A route is body prose with steps and a printed yield.

    A shared method sentence is kept verbatim, a bioassay section is never a
    route, and a passage that names no designation (a quantity is a mass) is
    reported unresolved rather than guessed.
    """
    section, blocks = _route_input(
        "example",
        "实施例7：化合物7的制备",
        ["步骤1：将中间体A与化合物B在室温下反应。", "步骤2：制得化合物7，收率72.3%。"],
    )

    routes = extract_synthesis_routes([section], blocks, "doc1")

    assert len(routes) == 1
    route = routes[0]
    assert route["step_count"] == 2
    assert route["steps"][0]["text"] == "步骤1：将中间体A与化合物B在室温下反应。"
    assert route["yield_raw"] == "收率72.3%"
    assert route["product_label"] == "化合物7"
    assert route["label_key"] == "7"
    assert route["attribution"] == "resolved"
    assert route["steps"][0]["evidence_ids"] == [section.evidence_ids[0]]

    shared, shared_blocks = _route_input(
        "preparation",
        "制备例3：化合物31的制备",
        [
            "The following compounds were synthesized using a similar method to that of Example 1.",
            "Step 1: A mixture of A and B was stirred.",
        ],
    )

    shared_routes = extract_synthesis_routes([shared], shared_blocks, "doc1")

    assert shared_routes[0]["method_note"] == (
        "The following compounds were synthesized using a similar method to that of Example 1."
    )
    assert shared_routes[0]["step_count"] == 1

    # A bioassay section mentions the compounds but prepares none of them.
    assay, assay_blocks = _route_input(
        "bioassay",
        "测试例1：MRGPRX2体外钙流测定试验",
        ["化合物1的IC50为60.7nM。", "结果表明本发明化合物具有良好的拮抗作用。"],
    )

    assert extract_synthesis_routes([assay], assay_blocks, "doc1") == []

    # ``制得化合物36.8mg`` prints a mass, not compound 36.
    quantity, quantity_blocks = _route_input(
        "example",
        "实施例1：化合物1的制备",
        ["参考实施例1方法，制得化合物36.8mg，收率16.5%。"],
    )

    quantity_routes = extract_synthesis_routes([quantity], quantity_blocks, "doc1")

    assert quantity_routes[0]["product_label"] == ""
    assert quantity_routes[0]["label_key"] == "@example:1"
    assert (
        quantity_routes[0]["method_note"]
        == "参考实施例1方法，制得化合物36.8mg，收率16.5%。"
    )

    unnamed, unnamed_blocks = _route_input(
        "example",
        "实施例",
        ["将中间体与酸反应，制得目标产物，收率41%。"],
    )

    unnamed_routes = extract_synthesis_routes([unnamed], unnamed_blocks, "doc1")

    assert unnamed_routes[0]["attribution"] == "unresolved"
    assert unnamed_routes[0]["label_key"] == ""


# ── printed characterization data (deterministic, zero-token) ────────


def _characterization_evidence(*lines: str) -> list[SourceEvidence]:
    return [
        SourceEvidence.create(
            doc_id="doc1",
            page=110 + index,
            bbox=(10.0, 800.0, 200.0, 820.0),
            raw_text=line,
        )
        for index, line in enumerate(lines)
    ]


def test_characterization_lines_are_kept_verbatim_with_their_owner() -> None:
    """Only a printed technique line is data; a mass reading is not.

    A designation that owns the line resolves it, an unattributed line stays
    unresolved, two designations leave the passage unattributed, and an example
    designation uses the example key space.
    """
    items = extract_characterization(
        _characterization_evidence(
            "化合物77：1H NMR (400 MHz, CDCl3) δ 7.42 (s, 1H), 6.98 (d, 1H), 3.85 (s, 3H)."
        ),
        "doc1",
    )
    assert len(items) == 1
    assert items[0]["technique"] == "nmr"
    assert items[0]["raw_text"] == (
        "化合物77：1H NMR (400 MHz, CDCl3) δ 7.42 (s, 1H), 6.98 (d, 1H), 3.85 (s, 3H)."
    )
    assert items[0]["label_key"] == "77"
    assert items[0]["attribution"] == "resolved"

    ms_items = extract_characterization(
        _characterization_evidence(
            "参考实施例1方法，制得化合物36.8mg，收率16.5%。",
            "MS (ESI) m/z: 456.2 [M+H]+",
        ),
        "doc1",
    )
    assert [item["technique"] for item in ms_items] == ["ms"]
    assert ms_items[0]["raw_text"] == "MS (ESI) m/z: 456.2 [M+H]+"
    assert ms_items[0]["attribution"] == "unresolved"

    two = extract_characterization(
        _characterization_evidence("化合物1和化合物2的MS (ESI) m/z: 456.2 [M+H]+"),
        "doc1",
    )
    assert two[0]["label_key"] == ""
    assert two[0]["attribution"] == "unresolved"

    example = extract_characterization(
        _characterization_evidence("实施例7：LCMS: m/z 329.0 [M+H]+"),
        "doc1",
    )
    assert example[0]["label_key"] == "@example:7"


# ── printed chemistry names (deterministic, zero-token) ──────────────


def test_a_printed_title_name_is_kept_verbatim_and_a_non_name_refused() -> None:
    """The title names the chemical; a heading that names none yields nothing.

    ``[0095] 实施例1N-((1R,3S)-3-氨基环己基)甲酰胺的合成`` (CN121270515A) runs the
    label straight into the name, which is still read as a name.
    """
    section, blocks = _route_input(
        "example",
        "实施例1：N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺",
        ["步骤1：将中间体与酸反应。"],
    )

    names = extract_compound_names([section], blocks, "doc1")

    assert names[0]["name_raw"] == "N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺"
    assert names[0]["label_key"] == "@example:1"

    running, running_blocks = _route_input(
        "example",
        "实施例1N-((1R,3S)-3-氨基环己基)甲酰胺的合成",
        ["步骤1：将中间体与酸反应。"],
    )

    running_names = extract_compound_names([running], running_blocks, "doc1")

    assert running_names[0]["name_raw"] == "N-((1R,3S)-3-氨基环己基)甲酰胺"
    assert running_names[0]["label_key"] == "@example:1"

    screening, screening_blocks = _route_input(
        "example",
        "Example 2: Screening of Compounds",
        ["Step 1: compounds were screened."],
    )

    assert extract_compound_names([screening], screening_blocks, "doc1") == []


def test_a_printed_mass_is_checked_against_the_structure() -> None:
    """Ethanol weighs 46.04: a printed 200.0 [M+H]+ is worth review, 47.0 is not."""

    class _Structure:
        mol_id = "MOL-77"
        canonical_smiles = "CCO"
        name = "77"
        properties = {"ocr_labels_primary": "77"}
        detections: list = []

    mismatches = find_mass_mismatches(
        [
            {
                "technique": "ms",
                "label_key": "77",
                "raw_text": "化合物77：MS (ESI) m/z: 200.0 [M+H]+",
                "evidence_ids": ["ev-ms"],
            }
        ],
        [_Structure()],
    )

    assert len(mismatches) == 1
    assert mismatches[0]["mol_id"] == "MOL-77"
    assert mismatches[0]["printed_mz"] == 200.0
    assert mismatches[0]["delta"] > 150  # ~152 Da off, nothing like a rounding error

    assert (
        find_mass_mismatches(
            [
                {
                    "technique": "ms",
                    "label_key": "77",
                    "raw_text": "化合物77：MS (ESI) m/z: 47.0 [M+H]+",
                    "evidence_ids": ["ev-ms"],
                }
            ],
            [_Structure()],
        )
        == []
    )


# ── the model's associations are consumed here (never a reading) ─────


def test_an_association_resolves_the_designation_and_binds_its_reading() -> None:
    """Everything one association does, in the key space Python owns.

    A designation the document prints is resolved in place and keeps both evidence
    rows; a designation no section declared becomes the entry the model declared, so
    the reading that cites it finally has something to join; the structure is stored
    in the identity persistence reads (canonical SMILES) even though the link named
    the ``mol_id``; an example keeps its own key space; a match the rules already
    made is never overwritten by a suggestion; and the reading that cites the
    resolved designation carries the structure afterwards.
    """
    entries = [
        {
            "entry_id": "en-7",
            "label_key": "@example:7",
            "evidence_ids": ["ev-a"],
            "entity_id": None,
            "structure_status": "missing",
            "linking_status": "unlinked",
        },
        {
            "entry_id": "en-77",
            "label_key": "77",
            "evidence_ids": ["ev-c"],
            "entity_id": "CCO",
            "structure_status": "resolved",
            "linking_status": "linked",
        },
    ]
    measurements = [
        {
            "measurement_id": "m-999",
            "mol_id": None,
            "linking_status": "failed",
            "provenance": {"reference_raw": "化合物999"},
        },
        {
            "measurement_id": "m-77",
            "mol_id": None,
            "linking_status": "failed",
            "provenance": {"reference_raw": "化合物77"},
        },
    ]
    section = ParsedSection(
        section_id="sec-1",
        title="实施例7：化合物77的制备",
        kind="example",
        page_start=1,
        page_end=1,
        raw_text="",
        labels=[],
        esmiles_candidate_ids=[],
        evidence_ids=["ev-b"],
        title_evidence_ids=["ev-b"],
        heading_line="实施例7：化合物77的制备",
    )

    applied = apply_gap_links(
        entries,
        [
            {"label_raw": "实施例7", "mol_id": "MOL-7", "evidence_ids": ["ev-b"]},
            {"label_raw": "化合物999", "mol_id": "MOL-999", "evidence_ids": ["ev-b"]},
            {"label_raw": "化合物77", "mol_id": "CCN", "evidence_ids": ["ev-d"]},
        ],
        doc_id="doc1",
        sections=[section],
        candidates=[
            Molecule(mol_id="MOL-999", canonical_smiles="CCO999"),
            Molecule(mol_id="MOL-7", canonical_smiles="CCO7"),
        ],
        measurements=measurements,
    )

    # The printed entry and the declared designation: two links applied.
    assert applied == 2
    assert entries[0]["entity_id"] == "CCO7"  # the mol_id resolved to its SMILES
    assert entries[0]["linking_status"] == "linked"
    assert entries[0]["evidence_ids"] == ["ev-a", "ev-b"]
    # A designation the rules already resolved is not overwritten by a suggestion.
    assert entries[1]["entity_id"] == "CCO"
    # The declared designation exists as an entry of its own, awaiting review.
    declared = entries[2]
    assert declared["label_raw"] == "化合物999"
    assert declared["label_key"] == "999"
    assert declared["entity_id"] == "CCO999"
    assert declared["section_id"] == "sec-1"
    assert declared["structure_status"] == "resolved"
    assert declared["linking_status"] == "linked"
    assert declared["review_status"] == "pending"
    assert declared["evidence_ids"] == ["ev-b"]
    # The reading that cites the resolved designation carries its structure.
    assert measurements[0]["mol_id"] == "CCO999"
    assert measurements[0]["linking_status"] == "linked"
    assert measurements[1]["mol_id"] is None


# ── stage execution + publication ───────────────────────────────────


def test_patent_stage_publishes_entries_assays_and_structure_free_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stage publishes facts at the document root, with the analyses implied.

    Evidence rebuild: entries survive with no structures, carry their source
    evidence, and their printed name; assay methods come from titles; and a
    molecule crop with an activity reading is associated and persisted to the
    molecule database — while a structure with no activity is not.
    """
    pages = [
        FakePage(1, "实施例1：化合物1的制备\n将原料溶于溶剂。"),
        FakePage(2, "实施例2：化合物2的制备\n收率 80%。"),
    ]
    ctx = _make_ctx(tmp_path, pages)
    blocks = _seed_evidence(tmp_path, pages)
    ctx.run_id = "runabc123"

    result = PatentStage().execute(ctx)

    assert result.status == "success"
    assert result.context["section_count"] == 2
    assert result.context["entry_count"] == 2

    artifact_path = tmp_path / "storage" / "doc1" / "patent_facts.json"
    assert artifact_path.is_file()
    assert result.context["artifact_path"] == str(artifact_path)
    assert not (tmp_path / "storage" / "doc1" / "runs").exists()

    facts = load_patent_facts(tmp_path, "doc1")
    assert facts is not None
    assert facts.run_id == "runabc123"
    assert [e["label_raw"] for e in facts.entries] == ["化合物1", "化合物2"]
    assert len(facts.examples) == 2
    assert "schema_version" not in facts.model_dump()
    assert "provenance" not in facts.model_dump()
    assert "raw_text" not in facts.sections[0].model_dump()

    # No structures at all: entries remain, carrying their source evidence.
    entry = facts.entries[0]
    assert entry["entity_id"] is None
    assert entry["structure_status"] == "missing"
    assert entry["evidence_ids"] == [blocks[0].evidence_id]

    assay_pages = [
        FakePage(1, "实施例1：化合物1的制备\n将原料溶于溶剂。"),
        FakePage(2, "实施例2：化合物5对MRGPRX2受体抑制活性\n测试化合物的作用。"),
    ]
    assay_root = tmp_path / "assay"
    assay_ctx = _make_ctx(assay_root, assay_pages)
    _seed_evidence(assay_root, assay_pages)
    assay_result = PatentStage().execute(assay_ctx)
    assert assay_result.status == "success"
    assert assay_result.context["assay_method_count"] == 1
    assert assay_result.context["entry_count"] == 2

    assay_facts = load_patent_facts(assay_root, "doc1")
    assert assay_facts is not None
    assert len(assay_facts.assay_methods) == 1
    method = assay_facts.assay_methods[0]
    assert method["target"] == "MRGPRX2"
    assert method["endpoint"] == "抑制活性"
    assert method["comparison_key"] is None
    assert method["page_start"] == 2
    assert [e["label_raw"] for e in assay_facts.entries] == ["化合物1", "化合物5"]

    # A structure plus a reading: the measurement is associated and persisted.
    heading = "实施例1：化合物20对MRGPRX2受体抑制活性"
    body = "化合物20的IC50为10 nM。"
    text_heading = SourceEvidence.create(
        doc_id="doc1",
        page=1,
        bbox=(10.0, 980.0, 200.0, 1000.0),
        raw_text=heading,
    )
    molecule_evidence = SourceEvidence.create(
        doc_id="doc1",
        page=1,
        bbox=(10.0, 940.0, 200.0, 960.0),
        raw_text="molecule crop",
        kind="molecule",
    )
    text_body = SourceEvidence.create(
        doc_id="doc1",
        page=1,
        bbox=(10.0, 900.0, 200.0, 920.0),
        raw_text=body,
    )
    link_root = tmp_path / "linked"
    persist_source_evidence(link_root, [text_heading, molecule_evidence, text_body])

    measurement = ActivityMeasurement(
        measurement_id="measurement-1",
        doc_id="doc1",
        metric="IC50",
        value=MeasurementValue(
            raw_text="10 nM",
            operator="=",
            original_value=Decimal("10"),
            original_unit="nM",
            canonical_value=Decimal("10"),
            canonical_unit="nM",
        ),
        evidence_ids=[text_body.evidence_id],
        provenance={"reference_raw": "化合物20"},
    ).to_dict()
    monkeypatch.setattr(
        "mbforge.service.pipeline.activity.extraction.extract_activity_measurements_from_evidence",
        lambda _evidence, _doc_id: ([measurement], []),
    )

    candidate = Molecule(
        canonical_smiles="CCO",
        esmiles="CCO",
        name="",
        sources=["image"],
        detections=[
            DetectionSource(
                source="image",
                page=0,
                bbox=molecule_evidence.bbox,
                evidence_id=molecule_evidence.evidence_id,
            )
        ],
        properties={"ocr_labels": ["化合物20"]},
    )
    link_ctx = _make_ctx(link_root, [FakePage(1, f"{heading}\n{body}")])
    link_ctx.candidates = [
        candidate,
        Molecule(
            canonical_smiles="*N",
            esmiles="*N",
            name="20",
            detections=candidate.detections,
        ),
        Molecule(
            canonical_smiles="CCN",
            esmiles="CCN",
            name="20",
            status="rejected",
            detections=candidate.detections,
        ),
    ]

    link_result = PatentStage().execute(link_ctx)

    assert link_result.status == "success"
    link_facts = load_patent_facts(link_root, "doc1")
    assert link_facts is not None
    linked_entry = link_facts.entries[0]
    saved_measurement = link_facts.measurements[0]
    assert linked_entry["entity_id"] == "CCO"
    assert saved_measurement["compound_entry_id"] == linked_entry["entry_id"]
    assert (
        saved_measurement["assay_method_id"]
        == link_facts.assay_methods[0]["assay_method_id"]
    )
    assert saved_measurement["linking_status"] == "linked"
    assert molecule_evidence.evidence_id in linked_entry["evidence_ids"]
    assert link_facts.issues == []
    assert link_result.context["molecule_count"] == 1
    with DatabaseManager.get(str(link_root)).mol_conn() as conn:
        molecule = conn.execute(
            "SELECT mol_id, smiles, activity, activity_type, units FROM molecules"
        ).fetchone()
    assert molecule is not None
    assert tuple(molecule) == ("CCO", "CCO", 10.0, "IC50", "nM")

    # A structure alone is not enough to enter the molecule database.
    monkeypatch.setattr(
        "mbforge.service.pipeline.activity.extraction.extract_activity_measurements_from_evidence",
        lambda _evidence, _doc_id: ([], []),
    )
    bare_root = tmp_path / "bare"
    bare_heading = SourceEvidence.create(
        doc_id="doc1",
        page=1,
        bbox=(10.0, 980.0, 200.0, 1000.0),
        raw_text="实施例1：化合物20的制备",
    )
    bare_molecule = SourceEvidence.create(
        doc_id="doc1",
        page=1,
        bbox=(10.0, 940.0, 200.0, 960.0),
        raw_text="molecule crop",
        kind="molecule",
    )
    persist_source_evidence(bare_root, [bare_heading, bare_molecule])
    bare_ctx = _make_ctx(bare_root, [FakePage(1, "实施例1：化合物20的制备")])
    bare_ctx.candidates = [
        Molecule(
            canonical_smiles="CCO",
            esmiles="CCO",
            name="",
            sources=["image"],
            detections=[
                DetectionSource(
                    source="image",
                    page=0,
                    bbox=bare_molecule.bbox,
                    evidence_id=bare_molecule.evidence_id,
                )
            ],
            properties={"ocr_labels": ["化合物20"]},
        )
    ]

    bare_result = PatentStage().execute(bare_ctx)

    assert bare_result.status == "success"
    assert bare_result.context["molecule_count"] == 0
    with DatabaseManager.get(str(bare_root)).mol_conn() as conn:
        assert conn.execute("SELECT 1 FROM molecules").fetchone() is None


def test_a_printed_name_fills_an_entry_that_has_none(tmp_path: Path) -> None:
    """The published facts carry the printed name, with the model switched off."""
    pages = [
        FakePage(
            1,
            "实施例1：N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺\n"
            "步骤1：将中间体与酸反应，收率41%。\n"
            "化合物1：1H NMR (400 MHz, CDCl3) δ 7.42 (s, 1H)。",
        )
    ]
    ctx = _make_ctx(tmp_path, pages)
    _seed_evidence(tmp_path, pages)

    PatentStage().execute(ctx)
    facts = load_patent_facts(tmp_path, "doc1")

    assert facts is not None
    assert facts.analysis_status == "disabled"
    assert facts.extraction_mode == "deterministic"
    assert facts.names[0]["name_raw"] == "N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺"
    assert facts.characterizations[0]["technique"] == "nmr"
    assert facts.synthesis_steps[0]["yield_raw"] == "收率41%"
    assert facts.synthesis_steps[0]["step_count"] == 1
    assert facts.stats["characterization_count"] == 1
    assert any(entry["label_key"] == "@example:1" for entry in facts.entries)
    assert any(entry["label_key"] == "1" for entry in facts.entries)


def test_patent_stage_does_not_invent_activity_pairs_from_mass_alone(
    tmp_path: Path,
) -> None:
    """A matching unnamed structure and MS line are not an activity reading.

    Existing stage coverage has no stored unnamed structure with a matching mass.
    This reproduces the recovery branch publishing an empty-measurement pair.
    """
    pages = [
        FakePage(
            1,
            "实施例1：2-羟基乙烷(化合物1)的制备\nLC-MS,M/Z(ESI):47.05[M+H]+",
        )
    ]
    _seed_evidence(tmp_path, pages)
    with DatabaseManager.get(str(tmp_path)).mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, canonical_smiles, source_doc) "
            "VALUES (?, ?, ?, ?)",
            ("unlabelled", "CCO", "CCO", "doc1"),
        )
        conn.commit()

    PatentStage().execute(_make_ctx(tmp_path, pages))
    facts = load_patent_facts(tmp_path, "doc1")

    assert facts is not None
    assert len(facts.characterizations) == 1
    assert facts.characterizations[0]["technique"] == "ms"
    assert facts.measurements == []
    assert facts.structure_activity == []


def test_patent_stage_requires_parsed_documents(tmp_path: Path) -> None:
    ctx = PipelineContext(
        pdf_path=tmp_path / "s.pdf", library_root=tmp_path, doc_id="d"
    )
    result = PatentStage().execute(ctx)
    assert result.status == "error"
    assert result.error_code == "MISSING_CONTEXT"


def test_republishing_replaces_the_document_artifact(tmp_path: Path) -> None:
    """Same-document republish replaces the artifact and never forks a run dir."""
    ctx = _make_ctx(tmp_path, [FakePage(1, "实施例1：化合物1的制备")])
    _seed_evidence(tmp_path, [FakePage(1, "实施例1：化合物1的制备")])
    PatentStage().execute(ctx)
    first = load_patent_facts(tmp_path, "doc1")
    assert first is not None
    first_run = first.run_id

    ctx.run_id = "runsecond"
    PatentStage().execute(ctx)
    second = load_patent_facts(tmp_path, "doc1")
    assert second is not None
    assert second.run_id == "runsecond" != first_run
    artifact_path = tmp_path / "storage" / "doc1" / "patent_facts.json"
    assert artifact_path.is_file()
    assert not (tmp_path / "storage" / "doc1" / "runs").exists()
    assert list(artifact_path.parent.glob("*.tmp")) == []


def test_the_artifact_store_tolerates_missing_corrupt_and_unpublished_docs(
    tmp_path: Path,
) -> None:
    assert load_patent_facts(tmp_path, "doc1") is None

    corrupt_root = tmp_path / "corrupt"
    corrupt = corrupt_root / "storage" / "doc1" / "patent_facts.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_patent_facts(corrupt_root, "doc1") is None

    for doc in ("a", "b"):
        p = tmp_path / "storage" / doc / "patent_facts.json"
        p.parent.mkdir(parents=True)
        p.write_text("{}", encoding="utf-8")
    (tmp_path / "storage" / "c").mkdir(parents=True)
    assert iter_published_doc_ids(tmp_path) == ["a", "b"]


def test_prose_compound_names_are_recovered_from_running_text() -> None:
    """A name printed in a preparation paragraph is recorded, not only a heading.

    Scanned patents frequently name their product mid-sentence and never draw its
    structure (a chiral SFC split reports only retention time and LC-MS). Reading
    headings alone left those compounds with no name at all — measured on
    CN120329282A, 190 of 1014 text rows carry a chemistry-name marker but only
    headings were read.
    """
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.service.pipeline.stages.patent_stage import (
        extract_prose_compound_names,
    )

    class _Register:
        pass

    from mbforge.domain.evidence_kind import register_kinds

    register_kinds({"text": "text"})
    block = SourceEvidence(
        doc_id="doc-1",
        page=7,
        bbox=(0.0, 0.0, 1.0, 1.0),
        evidence_id="ev-1",
        kind="text",
        raw_text=(
            "得到化合物N-((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己基)"
            "-3-(二甲基磷酰基)-1-(2,2,2-三氟乙基)-1H-吡唑-4-甲酰胺(化合物38)"
            "(12.6mg，产率9.5%)。"
        ),
    )

    names = extract_prose_compound_names([block], "doc-1")

    assert len(names) == 1
    recorded = names[0]["name_raw"]
    # The bracketed note after the name is not part of it.
    assert recorded.endswith("1H-吡唑-4-甲酰胺")
    assert "产率" not in recorded
    assert names[0]["evidence_ids"] == ["ev-1"]


def test_a_workup_sentence_is_not_recorded_as_a_compound_name() -> None:
    """``得到混合物在氮气保护下…`` is a step, not a chemistry name."""
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.domain.evidence_kind import register_kinds
    from mbforge.service.pipeline.stages.patent_stage import (
        extract_prose_compound_names,
    )

    register_kinds({"text": "text"})
    block = SourceEvidence(
        doc_id="doc-1",
        page=3,
        bbox=(0.0, 0.0, 1.0, 1.0),
        evidence_id="ev-2",
        kind="text",
        raw_text="得到混合物在氮气保护下于25℃搅拌18小时，然后过滤。",
    )

    assert extract_prose_compound_names([block], "doc-1") == []


def test_a_step_heading_gives_its_characterization_an_owner() -> None:
    """An MS line printed under a preparation heading belongs to that compound.

    A scanned patent stores the heading and the characterization line as separate
    evidence rows, so reading only the line leaves every mass unattributed — which
    silently disabled the printed-mass cross-check.
    """
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.domain.evidence_kind import register_kinds
    from mbforge.service.pipeline.stages.patent_stage import extract_characterization

    register_kinds({"text": "text"})
    heading = SourceEvidence(
        doc_id="doc-1",
        page=47,
        bbox=(0.0, 0.0, 1.0, 0.1),
        evidence_id="ev-head",
        kind="text",
        raw_text="第三步：叔丁基((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己烷)"
        "氨基甲酸酯(化合物8)的合成",
    )
    mass = SourceEvidence(
        doc_id="doc-1",
        page=47,
        bbox=(0.0, 0.1, 1.0, 0.2),
        evidence_id="ev-ms",
        kind="text",
        raw_text="[0168] LC-MS,M/Z(ESI):444.1[M+H]+",
    )

    items = extract_characterization([heading, mass], "doc-1")

    assert len(items) == 1
    assert items[0]["technique"] == "ms"
    assert items[0]["label_key"] == "8"
    assert items[0]["attribution"] == "resolved"


def test_a_reading_above_a_spectrum_does_not_lend_its_designation() -> None:
    """A reading's compound and a spectrum's compound need not be the same one.

    The spectrum stays unattributed so it surfaces as a gap; inheriting the
    reading's designation would bind a mass to the wrong structure and corrupt the
    check the mass feeds.
    """
    from mbforge.domain.evidence import SourceEvidence
    from mbforge.domain.evidence_kind import register_kinds
    from mbforge.service.pipeline.stages.patent_stage import extract_characterization

    register_kinds({"text": "text"})
    reading = SourceEvidence(
        doc_id="doc-1",
        page=5,
        bbox=(0.0, 0.0, 1.0, 0.1),
        evidence_id="ev-reading",
        kind="text",
        raw_text="化合物77的IC50为4 nM。",
    )
    spectrum = SourceEvidence(
        doc_id="doc-1",
        page=5,
        bbox=(0.0, 0.1, 1.0, 0.2),
        evidence_id="ev-ms",
        kind="text",
        raw_text="MS (ESI) m/z: 456.2 [M+H]+",
    )

    items = extract_characterization([reading, spectrum], "doc-1")

    assert len(items) == 1
    assert items[0]["label_key"] == ""
    assert items[0]["attribution"] == "unresolved"

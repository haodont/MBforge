"""Unit tests for the SQL-backed PatentStage facts boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from mbforge.core.activity import ActivityMeasurement, MeasurementValue
from mbforge.core.detection.types import DetectionSource, NormalizedMolecule
from mbforge.core.evidence import SourceEvidence
from mbforge.pipeline.context import PipelineContext
from mbforge.pipeline.extract_text import ExtractedDocument, PageContent
from mbforge.pipeline.patent_store import iter_published_doc_ids, load_patent_facts
from mbforge.pipeline.persist.source_evidence import persist_source_evidence
from mbforge.pipeline.stages.patent_stage import (
    PatentStage,
    extract_assay_method_from_title,
    extract_entries_from_title,
)
from mbforge.storage.sqlite.database import DatabaseManager


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
    """Keep Patent tests independent from Worker A's parallel module."""
    monkeypatch.setattr(
        "mbforge.pipeline.activity.extraction.extract_activity_measurements_from_evidence",
        lambda _evidence, _doc_id: ([], []),
        raising=False,
    )


# ── entry extraction ────────────────────────────────────────────────


def test_extract_entry_single_target_with_codes() -> None:
    entries = extract_entries_from_title(
        "实施例21：化合物23(IGP-20024-01)(A057-130)的制备", "d", "sec1", 21
    )
    assert len(entries) == 1
    e = entries[0]
    assert e["label_raw"] == "化合物23"
    assert e["entry_role"] == "preparation"
    assert e["name_raw"] == "IGP-20024-01 / A057-130"
    assert e["section_id"] == "sec1"
    assert e["evidence_ids"] == []


def test_extract_entries_multi_target() -> None:
    entries = extract_entries_from_title(
        "实施例13：化合物13和14的制备", "d", "sec1", 13
    )
    assert [e["label_raw"] for e in entries] == ["化合物13", "化合物14"]


def test_extract_entry_ids_deterministic() -> None:
    a = extract_entries_from_title("实施例1：化合物1的制备", "d", "s", 1)
    b = extract_entries_from_title("实施例1：化合物1的制备", "d", "s", 1)
    assert a[0]["entry_id"] == b[0]["entry_id"]


def test_extract_entry_bioassay_section_has_no_entries() -> None:
    assert (
        extract_entries_from_title("实施例27：化合物对MRGPRX2的抑制活性", "d", "s", 27)
        == []
    )


# ── assay method extraction ─────────────────────────────────────────


def test_extract_assay_method_from_title_with_target() -> None:
    title = "实施例27：化合物对MRGPRX2受体抑制活性"
    a = extract_assay_method_from_title(title, "d", "s27", 27, 29)
    b = extract_assay_method_from_title(title, "d", "s27", 27, 29)
    assert a is not None and b is not None
    assert a["target"] == "MRGPRX2"
    assert a["endpoint"] == "抑制活性"
    assert a["assay_method_id"] == b["assay_method_id"]
    assert a["comparison_key"] is None
    assert a["section_id"] == "s27"
    assert a["doc_id"] == "d"
    assert a["page_start"] == 27
    assert a["page_end"] == 29
    assert a["evidence_ids"] == []


def test_extract_assay_method_none_without_assay_hint() -> None:
    assert (
        extract_assay_method_from_title("实施例1：化合物1的制备", "d", "s", 1, 1)
        is None
    )


def test_extract_assay_method_type_from_latin_token() -> None:
    m = extract_assay_method_from_title(
        "实施例5：化合物对MRGPRX2受体(IC50)抑制活性", "d", "s5", 5, 5
    )
    assert m is not None and m["assay_type"] == "IC50"
    m2 = extract_assay_method_from_title(
        "实施例6：化合物对受体抑制活性(ic50)", "d", "s6", 6, 6
    )
    assert m2 is not None and m2["assay_type"] == "ic50"


# ── stage execution + publication ───────────────────────────────────


def test_patent_stage_publishes_facts_at_document_root(tmp_path: Path) -> None:
    pages = [
        FakePage(1, "实施例1：化合物1的制备\n将原料溶于溶剂。"),
        FakePage(2, "实施例2：化合物2的制备\n收率 80%。"),
    ]
    ctx = _make_ctx(tmp_path, pages)
    _seed_evidence(tmp_path, pages)
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


def test_patent_stage_entries_survive_without_structures(tmp_path: Path) -> None:
    """M1 acceptance: no structures at all — entries + raw text remain."""
    page = FakePage(1, "实施例1：化合物1的制备\n原料溶于溶剂。")
    ctx = _make_ctx(tmp_path, [page])
    blocks = _seed_evidence(tmp_path, [page])
    result = PatentStage().execute(ctx)
    assert result.status == "success"
    facts = load_patent_facts(tmp_path, "doc1")
    assert facts is not None and facts.entries
    entry = facts.entries[0]
    assert entry["entity_id"] is None
    assert entry["structure_status"] == "missing"
    assert entry["evidence_ids"] == [blocks[0].evidence_id]


def test_patent_stage_publishes_assay_methods_from_titles(tmp_path: Path) -> None:
    pages = [
        FakePage(1, "实施例1：化合物1的制备\n将原料溶于溶剂。"),
        FakePage(2, "实施例2：化合物5对MRGPRX2受体抑制活性\n测试化合物的作用。"),
    ]
    ctx = _make_ctx(tmp_path, pages)
    _seed_evidence(tmp_path, pages)
    result = PatentStage().execute(ctx)
    assert result.status == "success"
    assert result.context["assay_method_count"] == 1
    assert result.context["entry_count"] == 2

    facts = load_patent_facts(tmp_path, "doc1")
    assert facts is not None
    assert len(facts.assay_methods) == 1
    method = facts.assay_methods[0]
    assert method["target"] == "MRGPRX2"
    assert method["endpoint"] == "抑制活性"
    assert method["comparison_key"] is None
    assert method["page_start"] == 2
    assert [e["label_raw"] for e in facts.entries] == ["化合物1", "化合物5"]


def test_patent_stage_associates_measurement_assay_and_detection_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    persist_source_evidence(tmp_path, [text_heading, molecule_evidence, text_body])

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
        "mbforge.pipeline.activity.extraction.extract_activity_measurements_from_evidence",
        lambda _evidence, _doc_id: ([measurement], []),
    )

    candidate = NormalizedMolecule(
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
    ctx = _make_ctx(tmp_path, [FakePage(1, f"{heading}\n{body}")])
    ctx.candidates = [candidate]

    result = PatentStage().execute(ctx)

    assert result.status == "success"
    facts = load_patent_facts(tmp_path, "doc1")
    assert facts is not None
    entry = facts.entries[0]
    saved_measurement = facts.measurements[0]
    assert entry["entity_id"] == "CCO"
    assert saved_measurement["compound_entry_id"] == entry["entry_id"]
    assert (
        saved_measurement["assay_method_id"]
        == facts.assay_methods[0]["assay_method_id"]
    )
    assert saved_measurement["linking_status"] == "linked"
    assert molecule_evidence.evidence_id in entry["evidence_ids"]
    assert facts.issues == []
    assert result.context["molecule_count"] == 1
    with DatabaseManager.get(str(tmp_path)).mol_conn() as conn:
        molecule = conn.execute(
            "SELECT mol_id, smiles, activity, activity_type, units FROM molecules"
        ).fetchone()
    assert molecule is not None
    assert tuple(molecule) == ("CCO", "CCO", 10.0, "IC50", "nM")


def test_patent_stage_does_not_persist_structure_without_activity(
    tmp_path: Path,
) -> None:
    """A structure alone is not enough to enter the molecule database."""
    heading = SourceEvidence.create(
        doc_id="doc1",
        page=1,
        bbox=(10.0, 980.0, 200.0, 1000.0),
        raw_text="实施例1：化合物20的制备",
    )
    molecule_evidence = SourceEvidence.create(
        doc_id="doc1",
        page=1,
        bbox=(10.0, 940.0, 200.0, 960.0),
        raw_text="molecule crop",
        kind="molecule",
    )
    persist_source_evidence(tmp_path, [heading, molecule_evidence])

    candidate = NormalizedMolecule(
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
    ctx = _make_ctx(tmp_path, [FakePage(1, "实施例1：化合物20的制备")])
    ctx.candidates = [candidate]

    result = PatentStage().execute(ctx)

    assert result.status == "success"
    assert result.context["molecule_count"] == 0
    with DatabaseManager.get(str(tmp_path)).mol_conn() as conn:
        assert conn.execute("SELECT 1 FROM molecules").fetchone() is None


def test_patent_stage_missing_extracted_is_error(tmp_path: Path) -> None:
    ctx = PipelineContext(
        pdf_path=tmp_path / "s.pdf", library_root=tmp_path, doc_id="d"
    )
    result = PatentStage().execute(ctx)
    assert result.status == "error"
    assert result.error_code == "MISSING_CONTEXT"


def test_patent_store_returns_none_without_artifact(tmp_path: Path) -> None:
    assert load_patent_facts(tmp_path, "doc1") is None


def test_patent_store_returns_none_on_corrupt_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "storage" / "doc1" / "patent_facts.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{not json", encoding="utf-8")
    assert load_patent_facts(tmp_path, "doc1") is None


def test_iter_published_doc_ids_scans_storage(tmp_path: Path) -> None:
    for doc in ("a", "b"):
        p = tmp_path / "storage" / doc / "patent_facts.json"
        p.parent.mkdir(parents=True)
        p.write_text("{}", encoding="utf-8")
    (tmp_path / "storage" / "c").mkdir(parents=True)
    assert iter_published_doc_ids(tmp_path) == ["a", "b"]


def test_patent_stage_republish_replaces_document_artifact(tmp_path: Path) -> None:
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

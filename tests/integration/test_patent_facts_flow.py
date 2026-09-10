"""Integration: patent facts flow through the SQL-backed stage pipeline.

Uses a synthetic patent-style PDF with the heading patterns observed in
WO2026037254A1 (实施例N：化合物M的制备, OCR margin-noise prefixes) as
native text. The live WO PDF is validated manually (49-page OCR is too
slow for the suite); this test pins the file-first contract end to end.

"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mbforge.pipeline.patent_store import load_patent_facts
from mbforge.pipeline.stage_artifacts import load_document_evidence


def _run_all_stages(pdf_path: str, library_root: str, doc_id: str) -> str:
    """Drive the pipeline to completion; return the last completed stage."""
    from mbforge.pipeline.run_artifacts import staging_dir
    from mbforge.pipeline.runner import run_pipeline
    from mbforge.pipeline.stage_checkpoint import write_merged_report

    resume: str | None = None
    while True:
        result = run_pipeline(
            pdf_path, library_root, doc_id=doc_id, resume_from_stage=resume
        )
        if result.next_stage is None:
            break
        resume = result.current_stage
    # The worker normally writes the merged report; emulate it here.
    write_merged_report(
        staging_dir(library_root, doc_id), doc_id=doc_id, library_root=library_root
    )
    return result.current_stage or ""


@pytest.fixture(autouse=True)
def _activity_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep this stage-boundary test independent from Worker A's module."""
    monkeypatch.setattr(
        "mbforge.pipeline.activity.extraction.extract_activity_measurements_from_evidence",
        lambda _evidence, _doc_id: ([], []),
        raising=False,
    )


@pytest.fixture
def patent_pdf(tmp_path: Path) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "具体实施方式",
                "实施例1：化合物1的制备",
                "将中间体溶于四氢呋喃，搅拌过夜，收率 85%。",
                "20 实施例2：化合物2的制备",
                "氮气氛围下滴加试剂，收率 78%。",
                "实施例3：化合物对MRGPRX2受体抑制活性",
            ]
        ),
        fontsize=11,
        fontname="china-s",  # built-in CJK font; Helvetica drops Chinese glyphs
    )
    pdf_path = tmp_path / "patent.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_patent_facts_published_through_full_pipeline(
    patent_pdf: Path, tmp_path: Path
) -> None:
    library_root = tmp_path / "library"
    doc_id = "patentdoc"
    _run_all_stages(str(patent_pdf), str(library_root), doc_id)

    facts = load_patent_facts(library_root, doc_id)
    assert facts is not None
    assert [e["label_raw"] for e in facts.entries] == ["化合物1", "化合物2"]
    assert all(e["entity_id"] is None for e in facts.entries)
    assert all(e["structure_status"] == "missing" for e in facts.entries)
    assert [s.title for s in facts.sections][:2] == [
        "实施例1：化合物1的制备",
        "实施例2：化合物2的制备",
    ]
    assert len(facts.assay_methods) == 1
    assert facts.assay_methods[0]["target"] == "MRGPRX2"
    # Raw text stays addressable through the foundational evidence object.
    evidence = load_document_evidence(library_root, doc_id)
    assert evidence is not None
    entry_evidence = {item.evidence_id: item for item in evidence}
    assert (
        "实施例1：化合物1的制备"
        in entry_evidence[facts.entries[0]["evidence_ids"][0]].raw_text
    )

    artifact_path = library_root / "storage" / doc_id / "patent_facts.json"
    assert artifact_path.is_file()
    assert (
        json.loads(artifact_path.read_text(encoding="utf-8"))["run_id"] == facts.run_id
    )
    assert not (library_root / "storage" / doc_id / "runs").exists()

    # Merged report carries the patent stage.
    report = json.loads(
        (library_root / "storage" / doc_id / "document_report.json").read_text("utf-8")
    )
    assert report["stages"]["patent"]["status"] == "success"


def test_patent_entry_ids_stable_across_reruns(
    patent_pdf: Path, tmp_path: Path
) -> None:
    library_root = tmp_path / "library"
    doc_id = "rerun"
    _run_all_stages(str(patent_pdf), str(library_root), doc_id)
    first = load_patent_facts(library_root, doc_id)
    assert first is not None

    _run_all_stages(str(patent_pdf), str(library_root), doc_id)
    second = load_patent_facts(library_root, doc_id)
    assert second is not None

    assert [e["entry_id"] for e in first.entries] == [
        e["entry_id"] for e in second.entries
    ]
    assert second.run_id != first.run_id  # new publication, same content

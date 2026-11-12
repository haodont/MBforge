"""Unit tests for pipeline/stage_checkpoint.py.

Covers the staging summary read/write guards and the merged report writer
(which must agree with the API reader).
"""

from __future__ import annotations

import json
from pathlib import Path

from mbforge.service.pipeline.composition import effective_stage_names
from mbforge.service.pipeline.run.checkpoint import (
    collect_all_summaries,
    load_stage_summary,
    merge_report,
    save_stage_summary,
    write_merged_report,
)


def test_stage_summaries_round_trip_and_guard_missing_staging(tmp_path: Path) -> None:
    """Summaries round-trip their payload; a missing file/staging dir is quiet."""
    save_stage_summary(
        tmp_path,
        "extract",
        status="success",
        elapsed_ms=42,
        message="ok",
        context={"page_count": 5},
    )
    loaded = load_stage_summary(tmp_path, "extract")
    assert loaded is not None
    assert loaded["stage"] == "extract"
    assert loaded["status"] == "success"
    assert loaded["elapsed_ms"] == 42
    assert loaded["context"]["page_count"] == 5
    assert collect_all_summaries(tmp_path)["extract"]["elapsed_ms"] == 42

    save_stage_summary(
        tmp_path,
        "markdown",
        status="error",
        elapsed_ms=10,
        message="model missing",
        error_code="MOLDET_UNAVAILABLE",
    )
    loaded = load_stage_summary(tmp_path, "markdown")
    assert loaded is not None
    assert loaded["error_code"] == "MOLDET_UNAVAILABLE"
    assert set(collect_all_summaries(tmp_path)) == {"extract", "markdown"}

    assert load_stage_summary(tmp_path, "patent") is None
    assert load_stage_summary(None, "extract") is None
    save_stage_summary(None, "extract", status="success")  # must not raise
    assert collect_all_summaries(tmp_path / "absent") == {}


def _populate_all_stages(staging: Path) -> None:
    """Write success summaries for every stage with realistic context."""
    save_stage_summary(
        staging,
        "extract",
        status="success",
        elapsed_ms=100,
        context={"page_count": 3, "parser": "pymupdf", "title": "Test Doc"},
    )
    save_stage_summary(
        staging,
        "markdown",
        status="success",
        elapsed_ms=200,
        context={},
    )
    save_stage_summary(
        staging,
        "patent",
        status="success",
        elapsed_ms=10,
        context={"section_count": 1, "entry_count": 1},
    )


def test_merged_report_agrees_between_writer_and_reader(tmp_path: Path) -> None:
    """The merged report aggregates the summaries and lands on ``report.json``."""
    staging = tmp_path / "staging"
    staging.mkdir()
    _populate_all_stages(staging)

    report = merge_report(staging, doc_id="doc-1", library_root=str(tmp_path))
    assert report["doc_id"] == "doc-1"
    assert report["page_count"] == 3
    assert report["parser"] == "pymupdf"
    assert report["title"] == "Test Doc"
    assert report["duration_ms"] == 310  # 100+0+200+10
    assert report["molecule_count"] == 0
    assert report["activity_count"] == 0
    assert set(report["stages"].keys()) == set(effective_stage_names())
    assert "examples" not in report["stages"]

    # Set up a minimal library layout so LibraryLayout can resolve paths.
    library_root = tmp_path / "lib"
    library_root.mkdir()
    doc_id = "abc"
    storage = library_root / "storage" / doc_id
    storage.mkdir(parents=True)
    doc_staging = storage / ".staging"
    doc_staging.mkdir(parents=True)
    _populate_all_stages(doc_staging)

    report_path = write_merged_report(
        doc_staging, doc_id=doc_id, library_root=str(library_root)
    )
    assert report_path.is_file()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["doc_id"] == doc_id
    assert data["duration_ms"] == 310  # 100+0+200+10

    # Writer and reader must agree on the canonical artifact: the API reads
    # ``report.json``, so the merged report has to land exactly there.
    from mbforge.foundation.layout import LibraryLayout
    from mbforge.service.use_cases.documents.library import read_document_report

    assert report_path == LibraryLayout(str(library_root)).report_json(doc_id)
    assert (
        json.loads(read_document_report(str(library_root), doc_id))["doc_id"] == doc_id
    )

"""Unit tests for pipeline/stage_checkpoint.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mbforge.application.pipeline.composition import effective_stage_names
from mbforge.application.pipeline.run.checkpoint import (
    INCOMPATIBLE_CHECKPOINT,
    STAGE_ORDER,
    collect_all_summaries,
    ensure_run_checkpoint,
    is_last_stage,
    last_completed_stage,
    load_run_checkpoint,
    load_stage_summary,
    merge_report,
    next_stage,
    reset_stage_for_retry,
    save_stage_summary,
    summary_path,
    write_merged_report,
)

# ── next_stage ───────────────────────────────────────────────────────


def test_next_stage_from_none() -> None:
    assert next_stage(None) == "extract"


def test_next_stage_walks_order() -> None:
    assert next_stage("extract") == "detection"
    assert next_stage("detection") == "join"
    assert next_stage("join") == "markdown"
    assert next_stage("markdown") == "patent"
    assert next_stage("patent") is None


def test_next_stage_unknown_stage_restarts_from_extract() -> None:
    assert next_stage("persist") == "extract"


def test_next_stage_unknown_resets_to_extract() -> None:
    assert next_stage("bogus") == "extract"


# ── is_last_stage ────────────────────────────────────────────────────


def test_is_last_stage() -> None:
    assert not is_last_stage("extract")
    assert not is_last_stage("markdown")
    assert is_last_stage("patent")


# ── summary_path ─────────────────────────────────────────────────────


def test_summary_path_returns_expected(tmp_path: Path) -> None:
    p = summary_path(tmp_path, "markdown")
    assert p == tmp_path / "_stage_markdown.json"


# ── save / load stage summary ────────────────────────────────────────


def test_save_and_load_stage_summary(tmp_path: Path) -> None:
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


def test_save_summary_with_error_code(tmp_path: Path) -> None:
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


def test_load_summary_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_stage_summary(tmp_path, "persist") is None


def test_load_summary_none_staging_dir_returns_none() -> None:
    assert load_stage_summary(None, "extract") is None


def test_save_summary_none_staging_dir_is_noop() -> None:
    # Must not raise.
    save_stage_summary(None, "extract", status="success")


def test_run_checkpoint_reuses_id_and_records_stage_status(tmp_path: Path) -> None:
    run_id = ensure_run_checkpoint(tmp_path)
    assert ensure_run_checkpoint(tmp_path) == run_id

    save_stage_summary(tmp_path, "extract", status="running")
    checkpoint = load_run_checkpoint(tmp_path)
    assert checkpoint is not None
    assert checkpoint["run_id"] == run_id
    assert checkpoint["stages"]["extract"]["status"] == "running"


def test_old_stage_summary_is_not_auto_restarted(tmp_path: Path) -> None:
    save_stage_summary(tmp_path, "extract", status="success")

    with pytest.raises(RuntimeError, match=INCOMPATIBLE_CHECKPOINT):
        ensure_run_checkpoint(tmp_path)


def test_fresh_retry_reclaims_legacy_stage_summary(tmp_path: Path) -> None:
    """An explicit fresh retry replaces pre-v2 staging instead of failing again."""
    save_stage_summary(tmp_path, "extract", status="success")

    run_id = ensure_run_checkpoint(tmp_path, start_new=True)

    assert load_run_checkpoint(tmp_path)["run_id"] == run_id
    assert load_stage_summary(tmp_path, "extract") is None


def test_reset_retry_creates_checkpoint_when_staging_has_no_run_id(
    tmp_path: Path,
) -> None:
    """A manual retry after promotion must not leave summary-only staging."""
    reset_stage_for_retry(tmp_path, "extract")

    checkpoint = load_run_checkpoint(tmp_path)
    assert checkpoint is not None
    assert checkpoint["stages"] == {"extract": {"status": "pending"}}


# ── last_completed_stage ─────────────────────────────────────────────


def test_last_completed_stage_empty(tmp_path: Path) -> None:
    assert last_completed_stage(tmp_path) is None


def test_last_completed_stage_partial(tmp_path: Path) -> None:
    save_stage_summary(tmp_path, "extract", status="success")
    save_stage_summary(tmp_path, "detection", status="success")
    save_stage_summary(tmp_path, "join", status="success")
    save_stage_summary(tmp_path, "markdown", status="success")
    # patent missing → last completed is markdown
    assert last_completed_stage(tmp_path) == "markdown"


def test_last_completed_stage_all_done(tmp_path: Path) -> None:
    for name in STAGE_ORDER:
        save_stage_summary(tmp_path, name, status="success")
    assert last_completed_stage(tmp_path) == "patent"


def test_last_completed_stage_stops_at_failure(tmp_path: Path) -> None:
    save_stage_summary(tmp_path, "extract", status="success")
    save_stage_summary(tmp_path, "detection", status="success")
    save_stage_summary(tmp_path, "markdown", status="error")
    # Gap at markdown → only the two branches count as contiguous
    assert last_completed_stage(tmp_path) == "detection"


# ── collect_all_summaries ────────────────────────────────────────────


def test_collect_all_summaries(tmp_path: Path) -> None:
    save_stage_summary(tmp_path, "extract", status="success", elapsed_ms=10)
    save_stage_summary(tmp_path, "patent", status="success", elapsed_ms=20)
    result = collect_all_summaries(tmp_path)
    assert set(result.keys()) == {"extract", "patent"}
    assert result["extract"]["elapsed_ms"] == 10


def test_collect_all_summaries_empty(tmp_path: Path) -> None:
    assert collect_all_summaries(tmp_path) == {}


# ── merge_report / write_merged_report ────────────────────────────────


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
        "detection",
        status="success",
        elapsed_ms=150,
        context={"molecule_count": 2},
    )
    save_stage_summary(
        staging,
        "join",
        status="success",
        elapsed_ms=0,
        context={"source_evidence_count": 4},
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


def test_merge_report(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    _populate_all_stages(staging)

    report = merge_report(staging, doc_id="doc-1", library_root=str(tmp_path))
    assert report["doc_id"] == "doc-1"
    assert report["page_count"] == 3
    assert report["parser"] == "pymupdf"
    assert report["title"] == "Test Doc"
    assert report["duration_ms"] == 460  # 100+150+200+10
    assert report["molecule_count"] == 0
    assert report["activity_count"] == 0
    assert set(report["stages"].keys()) == set(effective_stage_names())
    assert "examples" not in report["stages"]


def test_write_merged_report(tmp_path: Path) -> None:
    # Set up a minimal library layout so LibraryLayout can resolve paths.
    library_root = tmp_path / "lib"
    library_root.mkdir()
    doc_id = "abc"
    storage = library_root / "storage" / doc_id
    storage.mkdir(parents=True)
    staging = storage / ".staging"
    staging.mkdir(parents=True)
    _populate_all_stages(staging)

    report_path = write_merged_report(
        staging, doc_id=doc_id, library_root=str(library_root)
    )
    assert report_path.is_file()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["doc_id"] == doc_id
    assert data["duration_ms"] == 460  # 100+150+200+10

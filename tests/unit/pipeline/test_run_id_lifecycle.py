"""Run-id lifecycle contract (per-stage single valid run id).

Protects the redesign rules:
- a run id is a UTC ``YYYYMMDDHHMMSS`` timestamp minted per worker claim;
- run IDs identify checkpoints and artifact contents, not the Patent artifact
  path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from mbforge.pipeline import run_ids as run_ids_module
from mbforge.pipeline.run_ids import mint_run_id
from mbforge.pipeline.stage_checkpoint import (
    begin_stage_run,
    latest_stage_run_id,
    load_run_checkpoint,
    save_stage_summary,
)
from mbforge.storage.layout import LibraryLayout

DOC = "doc-runid-lifecycle"


def test_mint_run_id_is_second_grained_and_avoids_existing_run_dirs(
    tmp_path: Path,
) -> None:
    """Minting returns ``YYYYMMDDHHMMSS`` and skips IDs already in use."""
    base = datetime(2026, 9, 9, 12, 34, 56, tzinfo=UTC)
    real_datetime = run_ids_module.datetime

    class _FrozenClock:
        @classmethod
        def now(cls, tz=UTC):  # noqa: ANN001
            return base if tz is UTC else base.astimezone(tz)

    run_ids_module.datetime = _FrozenClock  # type: ignore[assignment]
    try:
        layout = LibraryLayout(tmp_path)
        # Nothing occupied -> the base second is returned as-is.
        assert mint_run_id(tmp_path, DOC) == "20260909123456"

        # An existing run directory at the base second forces an advance.
        (layout.run_dir(DOC, "20260909123456")).mkdir(parents=True)
        assert mint_run_id(tmp_path, DOC) == "20260909123457"
        (layout.run_dir(DOC, "20260909123457")).mkdir(parents=True)
        staging = layout.storage_dir(DOC) / ".staging"
        staging.mkdir(parents=True)
        (staging / "_run.json").write_text(
            '{"run_id": "20260909123458"}', encoding="utf-8"
        )
        assert mint_run_id(tmp_path, DOC) == "20260909123459"
    finally:
        run_ids_module.datetime = real_datetime  # type: ignore[assignment]


def test_begin_stage_run_mints_fresh_id_each_claim_and_preserves_progress(
    tmp_path: Path,
) -> None:
    """Every claim (invocation) mints a fresh run id; stage progress survives."""
    staging = LibraryLayout(tmp_path).storage_dir(DOC) / ".staging"

    # Freeze the clock so two claims land in *different* seconds even though
    # they run back-to-back; otherwise same-second reuse is legal by design.
    base = datetime(2026, 9, 9, 12, 34, 56, tzinfo=UTC)
    real_datetime = run_ids_module.datetime

    class _AdvancingClock:
        _calls = 0

        @classmethod
        def now(cls, tz=UTC):  # noqa: ANN001
            cls._calls += 1
            return base + timedelta(seconds=cls._calls - 1)

    run_ids_module.datetime = _AdvancingClock  # type: ignore[assignment]
    try:
        first = begin_stage_run(staging, library_root=tmp_path, doc_id=DOC)
        assert first == "20260909123456"

        save_stage_summary(
            staging, "markdown", status="success", message="done", run_id=first
        )

        second = begin_stage_run(staging, library_root=tmp_path, doc_id=DOC)
        assert second == "20260909123457"
    finally:
        run_ids_module.datetime = real_datetime  # type: ignore[assignment]

    checkpoint = load_run_checkpoint(staging)
    assert checkpoint is not None
    assert checkpoint["run_id"] == second
    assert checkpoint["stages"]["markdown"] == {
        "status": "success",
        "run_id": first,
    }


def test_latest_stage_run_id_resolves_per_stage_and_falls_back_to_run_id(
    tmp_path: Path,
) -> None:
    """Per-stage summary run ids win; unknown stages fall back to the run id."""
    staging = LibraryLayout(tmp_path).storage_dir(DOC) / ".staging"
    run_id = begin_stage_run(staging, library_root=tmp_path, doc_id=DOC)
    save_stage_summary(staging, "patent", status="success", run_id=run_id)

    # Same stage, next claim: a second summary records the newer run id.
    newer = begin_stage_run(staging, library_root=tmp_path, doc_id=DOC)
    save_stage_summary(staging, "patent", status="success", run_id=newer)
    assert latest_stage_run_id(staging, "patent") == newer
    assert latest_stage_run_id(staging, "markdown") == newer  # top-level fallback

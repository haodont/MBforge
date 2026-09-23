"""Run-id lifecycle contract (one run id per ingestion attempt).

Protects the redesign rules:
- a run id is a UTC ``YYYYMMDDHHMMSS`` timestamp minted once per ingestion
  attempt and shared by every queue node of that attempt;
- binding the checkpoint to an attempt is idempotent while the run id is
  unchanged, and a *different* run id means a new attempt whose stale staging
  is discarded;
- run IDs identify checkpoints and artifact contents, not the Patent artifact
  path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mbforge.application.pipeline.run import ids as run_ids_module
from mbforge.application.pipeline.run.checkpoint import (
    ensure_attempt_run,
    latest_stage_run_id,
    load_run_checkpoint,
    save_stage_summary,
)
from mbforge.application.pipeline.run.ids import mint_run_id
from mbforge.foundation.layout import LibraryLayout

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


def test_ensure_attempt_run_binds_once_and_preserves_progress(
    tmp_path: Path,
) -> None:
    """Re-binding the same attempt keeps the checkpoint and its stage progress."""
    staging = LibraryLayout(tmp_path).storage_dir(DOC) / ".staging"
    run_id = "20260909123456"

    ensure_attempt_run(staging, run_id)
    save_stage_summary(
        staging, "extract", status="success", message="done", run_id=run_id
    )

    # Every node of the same attempt re-binds the same run id: no reset.
    ensure_attempt_run(staging, run_id)

    checkpoint = load_run_checkpoint(staging)
    assert checkpoint is not None
    assert checkpoint["run_id"] == run_id
    assert checkpoint["stages"]["extract"] == {"status": "success", "run_id": run_id}
    # The stage summary file itself is still on disk (staging not discarded).
    assert (staging / "_stage_extract.json").is_file()


def test_ensure_attempt_run_discards_stale_staging_for_new_run(
    tmp_path: Path,
) -> None:
    """A new attempt's run id wipes the previous attempt's staged artifacts."""
    staging = LibraryLayout(tmp_path).storage_dir(DOC) / ".staging"

    ensure_attempt_run(staging, "20260909123456")
    marker = staging / "extract.json"
    marker.write_text("{}", encoding="utf-8")

    ensure_attempt_run(staging, "20260909123457")

    assert not marker.exists()
    checkpoint = load_run_checkpoint(staging)
    assert checkpoint is not None
    assert checkpoint["run_id"] == "20260909123457"


def test_latest_stage_run_id_resolves_per_stage_and_falls_back_to_run_id(
    tmp_path: Path,
) -> None:
    """Per-stage summary run ids win; unrecorded stages fall back to the run id."""
    staging = LibraryLayout(tmp_path).storage_dir(DOC) / ".staging"
    attempt = "20260909123456"
    ensure_attempt_run(staging, attempt)

    save_stage_summary(staging, "patent", status="success", run_id=attempt)
    assert latest_stage_run_id(staging, "patent") == attempt

    # A later summary for the same stage records the newer run id.
    newer = "20260909123457"
    save_stage_summary(staging, "patent", status="success", run_id=newer)
    assert latest_stage_run_id(staging, "patent") == newer

    # A stage with no recorded run id falls back to the checkpoint's run id.
    assert latest_stage_run_id(staging, "markdown") == attempt

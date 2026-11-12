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

from mbforge.foundation.layout import LibraryLayout
from mbforge.service.pipeline.run import ids as run_ids_module
from mbforge.service.pipeline.run.checkpoint import (
    ensure_attempt_run,
    load_run_checkpoint,
    save_stage_summary,
)
from mbforge.service.pipeline.run.ids import mint_run_id

DOC = "doc-runid-lifecycle"


def test_mint_run_id_is_second_grained_and_avoids_existing_staged_ids(
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

        # A staged run ID at the base second forces an advance.
        staging = layout.storage_dir(DOC) / ".staging"
        staging.mkdir(parents=True)
        (staging / "_run.json").write_text(
            '{"run_id": "20260909123456"}', encoding="utf-8"
        )
        assert mint_run_id(tmp_path, DOC) == "20260909123457"
        (staging / "_run2.json").write_text(
            '{"run_id": "20260909123457"}', encoding="utf-8"
        )
        assert mint_run_id(tmp_path, DOC) == "20260909123458"
    finally:
        run_ids_module.datetime = real_datetime  # type: ignore[assignment]


def test_ensure_attempt_run_binds_once_and_discards_stale_staging(
    tmp_path: Path,
) -> None:
    """Re-binding the same attempt keeps progress; a new one wipes staging."""
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

    # A new attempt's run id wipes the previous attempt's staged artifacts.
    marker = staging / "extract.json"
    marker.write_text("{}", encoding="utf-8")

    newer_run = "20260909123457"
    ensure_attempt_run(staging, newer_run)

    assert not marker.exists()
    checkpoint = load_run_checkpoint(staging)
    assert checkpoint is not None
    assert checkpoint["run_id"] == newer_run

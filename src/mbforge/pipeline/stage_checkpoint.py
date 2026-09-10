"""Stage checkpoint management for stage-by-stage pipeline execution.

Each pipeline stage writes a lightweight summary file into the document's
staging directory (``storage/{doc_id}/.staging/``).  The branch artifacts
are stored as ``extract.json`` and ``detection.json`` in that directory. These
summaries serve two purposes:

1. **Observability** — every completed stage leaves a readable JSON
   artifact that can be inspected without parsing the full pipeline log.
2. **Restart** — when a pipeline is retried after failure, the runner
   reads the summaries to determine which stages already succeeded and
   skips them, continuing from the first incomplete stage.

The queue row's ``stage`` column tracks the *last completed* stage name.
On retry the column is NOT reset, so the runner can pick up where it
left off without re-running expensive stages (e.g. OCR extraction).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from ..core.stage import ORDER as _REGISTRY_ORDER
from ..utils.logger import get_logger

logger = get_logger("mbforge.pipeline.checkpoint")

# Canonical execution order, DERIVED from the stage registry
# (mbforge.core.stage — see TODO/services-layer-plan.md §4.2/§6.5).
# Importing the stage package here guarantees the registry is populated
# for every consumer of STAGE_ORDER (queue facade validation, checkpoint
# readers, tests) even when the runner has not been imported yet.
from . import stages as _stage_modules  # noqa: E402,F401  (triggers registration)
from .composition import effective_stage_names  # noqa: E402  (registration first)

# Registry order is the current execution order. Summary walks and next-stage
# decisions use ``effective_stage_names()`` so one composition controls both.
STAGE_ORDER: list[str] = _REGISTRY_ORDER

# Filename prefix for per-stage summary files inside the staging dir.
_SUMMARY_PREFIX = "_stage_"
_SUMMARY_SUFFIX = ".json"
_RUN_FILE = "_run.json"
_RUN_SCHEMA_VERSION = 2
INCOMPATIBLE_CHECKPOINT = "INCOMPATIBLE_CHECKPOINT"
_RUN_CHECKPOINT_LOCK = threading.Lock()


def run_checkpoint_path(staging_dir: Path | None) -> Path | None:
    """Return the durable run checkpoint path, or ``None`` without staging."""
    return staging_dir / _RUN_FILE if staging_dir is not None else None


def load_run_checkpoint(staging_dir: Path | None) -> dict[str, Any] | None:
    path = run_checkpoint_path(staging_dir)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"{INCOMPATIBLE_CHECKPOINT}: unreadable run checkpoint"
        ) from exc
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != _RUN_SCHEMA_VERSION
        or not isinstance(data.get("run_id"), str)
        or not data["run_id"]
    ):
        raise RuntimeError(f"{INCOMPATIBLE_CHECKPOINT}: invalid run checkpoint")
    return data


def _write_run_checkpoint(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_run_checkpoint(staging_dir: Path | None, *, start_new: bool = False) -> str:
    """Load the run ID, or start a new run after a completed checkpoint.

    A completed or incompatible checkpoint starts a fresh run only when
    ``start_new`` is true; incomplete v2 checkpoints remain resumable. A
    caller explicitly starting a new run may therefore recover legacy or
    corrupted staging, while normal resume still rejects it.
    """
    if staging_dir is None:
        return uuid.uuid4().hex[:16]

    try:
        existing = load_run_checkpoint(staging_dir)
    except RuntimeError:
        if not start_new:
            raise
        logger.warning("Discarding incompatible staging for fresh run: %s", staging_dir)
        shutil.rmtree(staging_dir)
        existing = None
    if existing is not None:
        statuses = existing.get("stages", {})
        complete = all(
            statuses.get(name, {}).get("status") == "success"
            for name in effective_stage_names()
        )
        if start_new and complete:
            shutil.rmtree(staging_dir)
            existing = None
        else:
            return existing["run_id"]

    if staging_dir.is_dir() and any(staging_dir.iterdir()):
        if not start_new:
            raise RuntimeError(f"{INCOMPATIBLE_CHECKPOINT}: staging has no run_id")
        logger.warning("Discarding legacy staging for fresh run: %s", staging_dir)
        shutil.rmtree(staging_dir)

    run_id = uuid.uuid4().hex[:16]
    path = run_checkpoint_path(staging_dir)
    assert path is not None
    _write_run_checkpoint(
        path,
        {"schema_version": _RUN_SCHEMA_VERSION, "run_id": run_id, "stages": {}},
    )
    return run_id


def _record_run_stage(
    staging_dir: Path | None, stage_name: str, status: str, run_id: str | None = None
) -> None:
    # ponytail: one process-wide lock is enough for the fixed two-branch fork;
    # use a file lock only if multiple runner processes ever share a checkpoint.
    with _RUN_CHECKPOINT_LOCK:
        data = load_run_checkpoint(staging_dir)
        if data is None:
            return
        entry: dict[str, str] = {"status": status}
        if run_id:
            entry["run_id"] = run_id
        data.setdefault("stages", {})[stage_name] = entry
        path = run_checkpoint_path(staging_dir)
        assert path is not None
        _write_run_checkpoint(path, data)


def begin_stage_run(
    staging_dir: Path | None,
    *,
    library_root: str | Path,
    doc_id: str,
    discard_completed: bool = False,
) -> str:
    """Begin a fresh stage run: mint a new run ID and rotate the checkpoint.

    Unlike :func:`ensure_run_checkpoint` (which reuses an existing run ID for
    resume), every invocation represents one worker claim / one stage run and
    therefore always mints a new timestamp run ID.  The checkpoint's
    ``stages{}`` progress map and any staged images are preserved — the
    staging directory is only discarded when a *fresh* start (explicit new
    ingestion, ``discard_completed``) meets an unusable leftover checkpoint.
    """
    from .run_ids import mint_run_id

    if staging_dir is None:
        return mint_run_id(library_root, doc_id)

    existing: dict[str, Any] | None = None
    try:
        existing = load_run_checkpoint(staging_dir)
    except RuntimeError:
        if not discard_completed:
            raise
        logger.warning("Discarding incompatible staging for fresh run: %s", staging_dir)
        shutil.rmtree(staging_dir)
        existing = None

    if existing is not None:
        statuses = existing.get("stages", {})
        complete = all(
            statuses.get(name, {}).get("status") == "success"
            for name in effective_stage_names()
        )
        if discard_completed and complete:
            # A previous whole-document run finished but was never promoted
            # (e.g. interrupted between the last stage and promotion).  Keep
            # the directory, reset the progress bookkeeping for the new run.
            logger.warning("Resetting completed staging for fresh run: %s", staging_dir)
            existing["stages"] = {}

    if existing is None and staging_dir.is_dir() and any(staging_dir.iterdir()):
        if not discard_completed:
            raise RuntimeError(f"{INCOMPATIBLE_CHECKPOINT}: staging has no run_id")
        logger.warning("Discarding legacy staging for fresh run: %s", staging_dir)
        shutil.rmtree(staging_dir)

    run_id = mint_run_id(library_root, doc_id)
    path = run_checkpoint_path(staging_dir)
    assert path is not None
    stages = existing.get("stages", {}) if existing is not None else {}
    for stage_name in (*effective_stage_names()[:2], "join"):
        stages.setdefault(stage_name, {"status": "pending"})
    _write_run_checkpoint(
        path,
        {
            "schema_version": _RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "stages": stages,
        },
    )
    return run_id


def latest_stage_run_id(staging_dir: Path | None, stage_name: str) -> str | None:
    """Return the most recent run ID recorded for *stage_name*.

    Reads ``stages[stage_name].run_id`` from the run checkpoint and falls
    back to the checkpoint's top-level ``run_id`` for legacy checkpoints
    that predate per-stage run IDs.
    """
    if staging_dir is None:
        return None
    data = load_run_checkpoint(staging_dir)
    if data is None:
        return None
    stage_entry = data.get("stages", {}).get(stage_name)
    if isinstance(stage_entry, dict):
        recorded = stage_entry.get("run_id")
        if isinstance(recorded, str) and recorded:
            return recorded
    top = data.get("run_id")
    return top if isinstance(top, str) and top else None


def next_stage(current: str | None) -> str | None:
    """Return the next *enabled* stage after *current*, or ``None`` at the end.

    Walks the composition-root effective order.

    >>> next_stage(None)
    'extract'
    >>> next_stage("extract")
    'markdown'
    >>> next_stage("patent")
    None
    """
    order = effective_stage_names()
    if current is None:
        return order[0] if order else None
    try:
        idx = order.index(current)
    except ValueError:
        # Unknown checkpoint (including a stage that has since been
        # disabled): restart from the beginning, mirroring the registry
        # semantics of ``core.stage.next_after``.
        return order[0] if order else None
    if idx + 1 < len(order):
        return order[idx + 1]
    return None


def is_last_stage(stage: str) -> bool:
    """Return True when *stage* is the final stage in the order."""
    order = effective_stage_names()
    return bool(order) and stage == order[-1]


def summary_path(staging_dir: Path | None, stage_name: str) -> Path | None:
    """Return the summary file path for *stage_name*, or None if no staging dir."""
    if staging_dir is None:
        return None
    return staging_dir / f"{_SUMMARY_PREFIX}{stage_name}{_SUMMARY_SUFFIX}"


def save_stage_summary(
    staging_dir: Path | None,
    stage_name: str,
    *,
    status: str,
    elapsed_ms: int = 0,
    message: str = "",
    context: dict[str, Any] | None = None,
    error_code: str | None = None,
    run_id: str | None = None,
) -> None:
    """Write a stage summary JSON file into the staging directory.

    The summary is a small, human-readable record of what the stage
    produced.  It is intentionally separate from the heavy artifacts
    (extracted text, molecule candidates) — those live in their own
    canonical locations; the summary only captures metadata and stats.
    ``run_id`` records the run ID of the stage invocation that wrote it.
    """
    path = summary_path(staging_dir, stage_name)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "stage": stage_name,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "message": message,
    }
    if run_id:
        payload["run_id"] = run_id
    if error_code:
        payload["error_code"] = error_code
    if context:
        payload["context"] = context
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _record_run_stage(staging_dir, stage_name, status, run_id)
    logger.debug("Stage summary saved: %s (%s)", path, status)


def reset_stage_for_retry(staging_dir: Path | None, stage_name: str) -> None:
    """Mark one stage pending so a manual retry is distinguishable from resume."""
    if staging_dir is None:
        return
    try:
        checkpoint = load_run_checkpoint(staging_dir)
    except RuntimeError:
        checkpoint = None
    if checkpoint is None:
        # An explicitly requested retry may follow a successful promotion,
        # which removes the transient staging directory, or an older staging
        # layout without a run checkpoint. Start a new checkpoint in place;
        # the runner will mint the claim's real run ID on the next invocation.
        path = run_checkpoint_path(staging_dir)
        assert path is not None
        _write_run_checkpoint(
            path,
            {
                "schema_version": _RUN_SCHEMA_VERSION,
                "run_id": uuid.uuid4().hex[:16],
                "stages": {},
            },
        )
        for name in (*effective_stage_names(), "join"):
            summary_path(staging_dir, name).unlink(missing_ok=True)
    summary = load_stage_summary(staging_dir, stage_name) or {"stage": stage_name}
    summary.update(
        {
            "stage": stage_name,
            "status": "pending",
            "elapsed_ms": 0,
            "message": "Waiting for retry",
        }
    )
    summary.pop("error_code", None)
    summary.pop("context", None)
    path = summary_path(staging_dir, stage_name)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _record_run_stage(staging_dir, stage_name, "pending")


def load_stage_summary(
    staging_dir: Path | None, stage_name: str
) -> dict[str, Any] | None:
    """Load a previously saved stage summary, or ``None`` if absent."""
    path = summary_path(staging_dir, stage_name)
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load stage summary %s: %s", path, exc)
        return None


def last_completed_stage(staging_dir: Path | None) -> str | None:
    """Determine the last successfully completed stage from summary files.

    Walks the effective stage order and returns the name of the last stage
    whose summary file exists with ``status == 'success'``.  Returns
    ``None`` when no stage has completed yet.
    """
    completed: str | None = None
    for name in effective_stage_names():
        summary = load_stage_summary(staging_dir, name)
        if summary is not None and summary.get("status") == "success":
            completed = name
        else:
            break
    return completed


def collect_all_summaries(
    staging_dir: Path | None,
) -> dict[str, dict[str, Any]]:
    """Load every stage summary into a ``{stage_name: payload}`` dict."""
    result: dict[str, dict[str, Any]] = {}
    for name in effective_stage_names():
        summary = load_stage_summary(staging_dir, name)
        if summary is not None:
            result[name] = summary
    return result


def merge_report(
    staging_dir: Path | None,
    *,
    doc_id: str,
    library_root: str | Path,
) -> dict[str, Any]:
    """Merge all stage summaries into a single readable report dict.

    The report is the authoritative ``document_report.json`` content.
    It consolidates per-stage timing, status, and statistics into one
    JSON-serializable dict that the caller writes to
    ``storage/{doc_id}/document_report.json``.
    """

    summaries = collect_all_summaries(staging_dir)
    stages_payload: dict[str, Any] = {}
    total_duration_ms = 0
    for name in effective_stage_names():
        s = summaries.get(name)
        if s is None:
            continue
        stages_payload[name] = {
            "status": s.get("status", "unknown"),
            "elapsed_ms": s.get("elapsed_ms", 0),
            "message": s.get("message", ""),
            "context": s.get("context"),
        }
        total_duration_ms += s.get("elapsed_ms", 0)

    # The current endpoint is Patent; later persistence will define its own
    # report projection.
    endpoint_ctx = summaries.get("patent", {}).get("context") or {}
    extract_ctx = summaries.get("extract", {}).get("context") or {}

    report: dict[str, Any] = {
        "doc_id": doc_id,
        "page_count": extract_ctx.get("page_count", 0),
        "parser": extract_ctx.get("parser", ""),
        "title": extract_ctx.get("title", ""),
        "duration_ms": total_duration_ms,
        "stages": stages_payload,
        "molecule_count": endpoint_ctx.get("molecule_count", 0),
        "activity_count": endpoint_ctx.get("measurement_count", 0),
        "structure_role_counts": endpoint_ctx.get("structure_role_counts"),
    }

    return report


def write_merged_report(
    staging_dir: Path | None,
    *,
    doc_id: str,
    library_root: str | Path,
) -> Path:
    """Write the merged report to ``storage/{doc_id}/document_report.json``.

    Returns the path of the written file.
    """
    from ..storage.layout import LibraryLayout

    report = merge_report(staging_dir, doc_id=doc_id, library_root=library_root)
    report_path = (
        LibraryLayout(library_root).storage_dir(doc_id) / "document_report.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Merged report written: %s", report_path)
    return report_path

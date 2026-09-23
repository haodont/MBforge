"""Pipeline event sink — single observability exit for the runner.

Consolidates the ``_maybe_record`` / ``_emit`` / ``_emit_stage_result`` closures
that used to live inside ``run_pipeline``: the ``on_progress`` callback, the
structured run logs, and the ``ingest_queue`` event recording (including the
terminal-status mapping and the diagnostics fallback on write failure).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mbforge.application.pipeline.run.checkpoint import STAGE_ORDER
from mbforge.application.pipeline.run.models import PipelineEvent, ProgressCallback
from mbforge.foundation.logger import get_logger

if TYPE_CHECKING:
    from mbforge.application.pipeline.stage import StageResult

logger = get_logger("mbforge.application.pipeline.runner")

# Map lifecycle events onto the ingest_queue terminal status so the UI reflects
# the actual run state instead of being stuck at "processing" forever.
# "start" opens the task, "complete" closes it as done, unrecoverable "error"
# aborts as failed, and "cancelled" keeps the queue terminal state at cancelled
# (distinct from ordinary failures). Intermediate warning/success events leave
# the status alone.
_STATUS_BY_EVENT = {
    "start": "processing",
    "complete": "done",
    "error": "failed",
    "cancelled": "cancelled",
}


class PipelineEventSink:
    """Routes pipeline lifecycle events to callback, logger, and ingest queue."""

    def __init__(
        self,
        on_progress: ProgressCallback | None,
        task_id: str | None,
        library_root: str | Path,
        doc_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.on_progress = on_progress
        self.task_id = task_id
        self.run_id = run_id
        self.library_root = str(library_root)
        self.doc_id = doc_id

    def _record(
        self, event: str, message: str, *, stage: str | None, data: dict | None
    ) -> None:
        """Persist one event to ``ingest_logs`` / mirror it onto the queue row."""
        if self.task_id is None:
            return
        try:
            from mbforge.application.ports import get_database

            get_database(self.library_root).record_ingest_event(
                task_id=self.task_id,
                run_id=self.run_id,
                doc_id=self.doc_id or None,
                stage=stage or "pipeline",
                level=event,
                message=message,
                data=data,
                status=_STATUS_BY_EVENT.get(event),
                update_stage=(stage if stage and stage in STAGE_ORDER else None),
            )
        except Exception as exc:  # noqa: BLE001 — observability must not abort work
            logger.warning("record_ingest_event failed: %s", exc)
            try:
                from mbforge.foundation.logger import push_diagnostic

                push_diagnostic(
                    {
                        "level": "WARNING",
                        "message": f"record_ingest_event failed: {exc}",
                        "category": "pipeline.runner",
                        "error_code": "ingest_log_write_failed",
                    }
                )
            except Exception:  # pragma: no cover
                pass

    def emit(
        self, event: str, message: str = "", *, stage: str | None = None, **data: Any
    ) -> None:
        """Emit a pipeline event to the callback, logger, and ingest queue."""
        if self.on_progress:
            try:
                self.on_progress(
                    PipelineEvent(
                        stage=stage or "pipeline",
                        event=event,
                        message=message,
                        data=data,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — observability must not abort work
                logger.warning("Pipeline event callback failed: %s", exc)
        if event == "error" or data.get("error"):
            logger.error("[%s] %s", event, message)
        elif stage not in {"extract", "detection"}:
            logger.info("[%s] %s", event, message)
        self._record(event, message, stage=stage, data=data or None)

    def emit_stage_result(self, result: StageResult) -> None:
        """Emit a pipeline event from a ``StageResult``."""
        data: dict[str, Any] = dict(result.context)
        if result.error_code:
            data["error_code"] = result.error_code
        data["recoverable"] = result.recoverable
        if result.warnings:
            data["warnings"] = list(result.warnings)
        event_name = "warning" if result.recoverable else result.status
        self.emit(event_name, result.message, stage=result.stage, **data)


__all__ = ["PipelineEventSink"]

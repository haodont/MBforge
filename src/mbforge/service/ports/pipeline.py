"""Pipeline runtime port (server -> service boundary).

The ingest worker and queue (server layer) drive the pipeline and read its
stage DAG, but they must not reach into the pipeline's internal modules. This
port is the contract they depend on; the concrete implementation lives in
:mod:`mbforge.service.pipeline.runtime` and is installed by the composition
root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

# Distinct error code for user cancellation; ordinary failures keep their
# stage-specific codes so the queue can tell the two terminal states apart.
PIPELINE_CANCELLED = "PIPELINE_CANCELLED"


class TaskCancelledError(RuntimeError):
    """Raised at a cooperative checkpoint after the user cancels a task."""

    error_code = PIPELINE_CANCELLED

    def __init__(self, task_id: str | None = None) -> None:
        super().__init__("Pipeline cancelled by user")
        self.task_id = task_id


class PipelineRuntime(Protocol):
    """Pipeline operations the server runtime needs, without its internals."""

    def stage_dependencies(self) -> dict[str, tuple[str, ...]]: ...

    def run_pipeline(
        self,
        pdf_path: str,
        library_root: str,
        doc_id: str = "",
        *,
        stage: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        on_progress: Any | None = None,
    ) -> Any: ...

    def cancel_task(self, task_id: str) -> None: ...

    def release_task(self, task_id: str | None) -> None: ...

    def staging_dir(self, library_root: str | Path, doc_id: str) -> Path: ...

    def promote_staging(
        self, staging: Path | None, library_root: str | Path, doc_id: str
    ) -> None: ...

    def write_merged_report(
        self, staging: Path | None, *, doc_id: str, library_root: str | Path
    ) -> Path: ...


_runtime: PipelineRuntime | None = None


def configure_pipeline_runtime(runtime: PipelineRuntime) -> None:
    """Install the concrete pipeline runtime during composition."""

    global _runtime
    _runtime = runtime


def get_pipeline_runtime() -> PipelineRuntime:
    """Return the configured pipeline runtime."""

    if _runtime is None:
        raise RuntimeError(
            "pipeline runtime is not configured; build the application through "
            "mbforge.server.app or configure it in the test composition root"
        )
    return _runtime


__all__ = [
    "PIPELINE_CANCELLED",
    "PipelineRuntime",
    "TaskCancelledError",
    "configure_pipeline_runtime",
    "get_pipeline_runtime",
]

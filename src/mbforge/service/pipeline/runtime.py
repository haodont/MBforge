"""Concrete ``PipelineRuntime`` backed by the pipeline implementation.

Installed by the composition root so the server layer (ingest worker/queue)
can drive the pipeline through the port instead of importing its internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ServicePipelineRuntime:
    """Delegates the pipeline runtime port to the pipeline modules."""

    def stage_dependencies(self) -> dict[str, tuple[str, ...]]:
        from mbforge.service.pipeline.composition import stage_dependencies

        return stage_dependencies()

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
    ) -> Any:
        from mbforge.service.pipeline.runner import run_pipeline

        return run_pipeline(
            pdf_path,
            library_root,
            doc_id,
            stage=stage,
            run_id=run_id,
            task_id=task_id,
            on_progress=on_progress,
        )

    def cancel_task(self, task_id: str) -> None:
        from mbforge.service.pipeline.runner import cancel_task

        cancel_task(task_id)

    def release_task(self, task_id: str | None) -> None:
        from mbforge.service.pipeline.runner import release_task

        release_task(task_id)

    def staging_dir(self, library_root: str | Path, doc_id: str) -> Path:
        from mbforge.service.pipeline.artifacts.staging import staging_dir

        return staging_dir(library_root, doc_id)

    def promote_staging(
        self, staging: Path | None, library_root: str | Path, doc_id: str
    ) -> None:
        from mbforge.service.pipeline.artifacts.staging import promote_staging

        promote_staging(staging, library_root, doc_id)

    def write_merged_report(
        self, staging: Path | None, *, doc_id: str, library_root: str | Path
    ) -> Path:
        from mbforge.service.pipeline.run.checkpoint import write_merged_report

        return write_merged_report(staging, doc_id=doc_id, library_root=library_root)


def create_pipeline_runtime() -> ServicePipelineRuntime:
    """Build the default pipeline runtime implementation."""
    return ServicePipelineRuntime()


__all__ = ["ServicePipelineRuntime", "create_pipeline_runtime"]

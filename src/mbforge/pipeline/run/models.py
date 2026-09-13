"""Runner DTOs shared between the pipeline runner and the queue worker.

These used to live in ``runner.py``; they are re-exported there so all
existing ``from mbforge.pipeline.runner import ...`` imports keep working.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class PipelineEvent:
    stage: str
    event: str | None = None
    message: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    doc_id: str
    page_count: int = 0
    parser: str = ""
    title: str = ""
    duration_ms: int = 0
    stage_timings: dict[str, int] = field(default_factory=dict)
    current_stage: str | None = None
    """The stage that just completed in this invocation."""
    next_stage: str | None = None
    """The stage the worker should re-queue for, or None when all done."""
    run_id: str | None = None
    """Durable run identity reused across stage invocations and retries."""


ProgressCallback = Callable[[PipelineEvent], None]


__all__ = ["PipelineEvent", "PipelineResult", "ProgressCallback"]

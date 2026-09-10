"""Base protocol for pipeline stage executors.

Defines the StageExecutor interface used by the pipeline runner.
Each stage reads from and writes to PipelineContext, returning a
StageResult so the runner can track stage outcomes and handle failures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..context import PipelineContext
    from ..stage_result import StageResult


@runtime_checkable
class StageExecutor(Protocol):
    """Protocol for pipeline stage executors.

    Each stage implements:
    - ``name``: stable stage identifier (matches STAGE_ORDER entries and
      the stage reported in its StageResult) used for checkpoints and resume
      — never derived from the class name.
    - execute(ctx) → StageResult
    - Reads from ctx, modifies ctx in-place, returns result

    Example:
        class ExtractStage:
            name = "extract"

            def execute(self, ctx: PipelineContext) -> StageResult:
                from ..extract_text import extract_pdf_text
                ctx.extracted = extract_pdf_text(str(ctx.pdf_path), ...)
                return StageResult(stage="extract", status="success", ...)
    """

    name: ClassVar[str]

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Execute this pipeline stage.

        Args:
            ctx: Shared pipeline context (read + write)

        Returns:
            StageResult with status/message/error_code

        Raises:
            Exception: Fatal errors that should abort the pipeline
        """
        ...

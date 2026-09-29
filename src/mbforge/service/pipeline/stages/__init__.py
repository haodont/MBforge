"""Pipeline stages — modular executors for document processing.

Each stage is a self-contained class implementing the ``StageExecutor``
protocol defined in :mod:`mbforge.service.pipeline.stage`:
- Reads from PipelineContext
- Performs one logical step
- Writes results back to PipelineContext
- Returns StageResult

Usage:
    from mbforge.service.pipeline.stages import ExtractStage, MarkdownStage

    ctx = PipelineContext(...)
    stage = ExtractStage()
    result = stage.execute(ctx)
"""

# Import order = registration order = pipeline execution order. Patent is the
# current pipeline endpoint.
# ruff: noqa: I001
from mbforge.service.pipeline.stages.extract_stage import ExtractStage
from mbforge.service.pipeline.stages.markdown_stage import MarkdownStage
from mbforge.service.pipeline.stages.patent_stage import PatentStage

__all__ = [
    "ExtractStage",
    "MarkdownStage",
    "PatentStage",
]

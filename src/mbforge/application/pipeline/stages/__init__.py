"""Pipeline stages — modular executors for document processing.

Each stage is a self-contained class implementing the ``StageExecutor``
protocol defined in :mod:`mbforge.application.pipeline.stage`:
- Reads from PipelineContext
- Performs one logical step
- Writes results back to PipelineContext
- Returns StageResult

Usage:
    from mbforge.application.pipeline.stages.stages import ExtractStage, MarkdownStage, PatentStage

    ctx = PipelineContext(...)
    stage = ExtractStage()
    result = stage.execute(ctx)
"""

# Import order = registration order = pipeline execution order. Patent is the
# current pipeline endpoint; Persist remains an unregistered future module.
# ruff: noqa: I001
from mbforge.application.pipeline.stages.extract_stage import ExtractStage
from mbforge.application.pipeline.stages.detection_stage import DetectionStage
from mbforge.application.pipeline.stages.join_stage import JoinStage
from mbforge.application.pipeline.stages.markdown_stage import MarkdownStage
from mbforge.application.pipeline.stages.patent_stage import PatentStage

__all__ = [
    "ExtractStage",
    "MarkdownStage",
    "DetectionStage",
    "JoinStage",
    "PatentStage",
]

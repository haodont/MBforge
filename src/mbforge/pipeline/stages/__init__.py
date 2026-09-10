"""Pipeline stages — modular executors for document processing.

Each stage is a self-contained class implementing the StageExecutor protocol:
- Reads from PipelineContext
- Performs one logical step
- Writes results back to PipelineContext
- Returns StageResult

Usage:
    from .stages import ExtractStage, MarkdownStage, PatentStage

    ctx = PipelineContext(...)
    stage = ExtractStage()
    result = stage.execute(ctx)
"""

# Import order = registration order = pipeline execution order. Patent is the
# current pipeline endpoint; Persist remains an unregistered future module.
# ruff: noqa: I001
from .extract_stage import ExtractStage
from .detection_stage import DetectionStage
from .markdown_stage import MarkdownStage
from .patent_stage import PatentStage
from .base import StageExecutor

__all__ = [
    "StageExecutor",
    "ExtractStage",
    "MarkdownStage",
    "DetectionStage",
    "PatentStage",
]

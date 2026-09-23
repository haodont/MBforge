"""MBForge document processing pipeline.

Orchestrates PDF ingestion, text and molecule extraction, document Markdown,
activity extraction, and persistence into the MBForge library. Stages
run sequentially through a modular StageExecutor registry and share state via
PipelineContext.
"""

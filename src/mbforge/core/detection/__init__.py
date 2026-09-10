"""Detection domain value objects shared across pipeline, storage and backends.

``NormalizedMolecule`` / ``DetectionSource`` / ``ExtractionResult`` are the
canonical contract between the pipeline (which builds the records), the
model backends (which produce them) and the persistence/review layers
(which consume them). They live in :mod:`mbforge.core` because they are
pure dataclasses with no pipeline or I/O dependencies.

The pipeline-side ``detection.types`` module re-exports these names so the
historical import paths keep working.
"""

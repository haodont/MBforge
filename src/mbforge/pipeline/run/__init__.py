"""Runner subpackage — decomposed orchestration for ``pipeline.runner.run_pipeline``.

Split the monolithic ``run_pipeline`` into focused collaborators:

- ``models``: the DTOs the runner exchanges with the queue worker.
- ``events``: ``PipelineEventSink`` (observability / ingest_queue recording).
- ``state``: ``RunContext`` (per-invocation orchestration state).
- ``initial_fork``: ``InitialForkRunner`` (Extract ∥ Detection fork + join).
- ``sequential``: ``SequentialStageRunner`` (resume/skip + one-stage loop).
- ``finalize``: ``Finalizer`` (run completion and failure/cancel cleanup).

Public symbols stay importable from ``mbforge.pipeline.runner``.
"""

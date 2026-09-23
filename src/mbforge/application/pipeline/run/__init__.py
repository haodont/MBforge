"""Runner subpackage — decomposed orchestration for ``pipeline.runner.run_pipeline``.

Split the monolithic ``run_pipeline`` into focused collaborators:

- ``models``: the DTOs the runner exchanges with the queue worker.
- ``events``: ``PipelineEventSink`` (observability / ingest_queue recording).
- ``context``: ``PipelineContext`` and ``RunContext`` (shared and per-invocation state).
- ``sequential``: ``StageRunner`` (executes the one stage the queue claimed).
- ``finalize``: ``Finalizer`` (run completion and failure/cancel cleanup).

Public symbols stay importable from ``mbforge.application.pipeline.runner``.
"""

"""Ingest executor — queue worker and queue DAO (infra layer).

Moved from ``services/ingest_worker.py`` / ``services/ingest_queue.py``
(TODO/services-layer-plan.md A6). Process-level execution concerns live
here; use-case orchestration lives in
:mod:`mbforge.services.pipeline.ingest`.
"""

from . import queue, worker  # noqa: F401

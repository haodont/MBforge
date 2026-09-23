"""Ingest executor — queue worker and queue DAO (infra layer).

Process-level execution concerns live here; use-case orchestration lives in
:mod:`mbforge.application.use_cases.pipeline.ingest`.
"""

from mbforge.adapters.runtime.ingest import queue, worker  # noqa: F401

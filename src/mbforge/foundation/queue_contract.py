"""Shared ingest queue state vocabulary."""

from __future__ import annotations

INGEST_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})

__all__ = ["INGEST_TERMINAL_STATUSES"]

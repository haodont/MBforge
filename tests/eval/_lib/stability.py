"""Stability / operational metric catalog (golden-agnostic).

The candidate ``run_summary.json`` must carry every declared metric to
pass ``validate_run_summary``. No metric is required to be present yet —
stability claims only become meaningful after we accumulate several
runs against the same golden document.
"""

from __future__ import annotations

from typing import Any

STABILITY_METRICS: dict[str, str] = {
    "run_id": "Stable identifier for the pipeline run (UUID v4).",
    "doc_id": "Document id assigned by MBForge (matches ArtifactResolver).",
    "started_at": "ISO-8601 UTC timestamp marking run start.",
    "finished_at": "ISO-8601 UTC timestamp marking run completion.",
    "total_seconds": "Wall-clock duration in seconds.",
    "pdf_page_count": "Number of pages in the source PDF.",
    "status": "Final pipeline status (ok / partial / failed).",
    "requests_total": "Total outbound provider requests.",
    "requests_failed": "Requests that returned a non-recoverable error.",
    "requests_429": "Requests that returned HTTP 429.",
    "retries_total": "Retries performed across all stages.",
    "tokens_in": "Total input tokens consumed.",
    "tokens_out": "Total output tokens generated.",
    "usd_estimated": "Estimated cost in USD based on provider pricing.",
    "checkpoint_resume_count": "Number of times the run resumed from a checkpoint.",
    "error_count": "Number of MBForgeError instances raised.",
}


def validate_run_summary(summary: dict[str, Any]) -> list[str]:
    """Return the list of stability metrics absent from ``summary``.

    Empty return value means the run summary covers every declared
    stability metric. The validator does not enforce types — downstream
    ingestion (Grafana, sqlite stats) handles that.
    """
    return [name for name in STABILITY_METRICS if name not in summary]

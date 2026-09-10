"""Stability / operational metrics schema.

The activity, molecule, and Markush evaluators score correctness. This
module describes the operational metrics that a real pipeline run should
emit in its run-summary JSON:

    run_id, doc_id, started_at, finished_at, total_seconds,
    pdf_page_count, status, requests_total, requests_failed,
    requests_429, retries_total, tokens_in, tokens_out, usd_estimated,
    checkpoint_resume_count, error_count

A candidate ``run_summary.json`` file with that schema can be validated
against the declared metric names. No metric is required to be present
yet — stability claims only become meaningful after we accumulate
several runs against the same golden document.
"""

from __future__ import annotations

from typing import Any

# Metric names declared by the eval suite. Each entry is a human-readable
# description that downstream reporting tooling (Grafana, Markdown
# reports, etc.) can reference.
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
    missing = [name for name in STABILITY_METRICS if name not in summary]
    return missing


def test_stability_metric_catalog_is_stable():
    """The declared metric catalog must remain a frozen schema."""
    expected = {
        "run_id",
        "doc_id",
        "started_at",
        "finished_at",
        "total_seconds",
        "pdf_page_count",
        "status",
        "requests_total",
        "requests_failed",
        "requests_429",
        "retries_total",
        "tokens_in",
        "tokens_out",
        "usd_estimated",
        "checkpoint_resume_count",
        "error_count",
    }
    assert set(STABILITY_METRICS) == expected


def test_validate_run_summary_reports_missing_keys():
    summary = {"run_id": "abc", "doc_id": "US20260027089A1"}
    missing = validate_run_summary(summary)
    assert "started_at" in missing
    assert "tokens_in" in missing

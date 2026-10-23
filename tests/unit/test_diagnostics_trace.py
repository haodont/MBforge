"""Diagnostics trace correlation + export regression tests.

Covers item 11 of the audit: every diagnostic record should be correlatable
across a run via doc_id, and the ring buffer must be exportable to a durable
JSON snapshot before process restart.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.foundation.logger import (
    JsonFormatter,
    reset_trace,
    set_trace,
)


def _log_record(
    name: str = "mbforge.test.trace",
    level: int = logging.ERROR,
    message: str = "boom",
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_json_formatter_emits_single_line_trace_fields_and_restores_context() -> None:
    """Rendered lines carry the structured schema + trace correlation, and
    ``reset_trace`` restores the previous (empty) correlation."""
    formatter = JsonFormatter()
    token = set_trace(doc_id="doc-42")
    try:
        rendered = formatter.format(_log_record())
        assert json.loads(rendered)["doc_id"] == "doc-42"
    finally:
        reset_trace(token)

    # Single-line JSON must carry the structured schema + trace correlation.
    payload = json.loads(rendered)
    assert payload["doc_id"] == "doc-42"
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "mbforge.test.trace"
    assert payload["message"] == "boom"

    # A second trace is visible while set, and gone after reset.
    token = set_trace(doc_id="doc-1")
    try:
        assert json.loads(formatter.format(_log_record()))["doc_id"] == "doc-1"
    finally:
        reset_trace(token)
    assert json.loads(formatter.format(_log_record()))["doc_id"] is None


def test_push_diagnostic_preserves_trace_fields(tmp_path: Path) -> None:
    """push_diagnostic passes caller-supplied doc_id through."""
    from mbforge.foundation.logger import get_diagnostic_by_id, push_diagnostic

    seq = push_diagnostic(
        {
            "level": "WARNING",
            "message": "provider retry exhausted",
            "category": "backends.ocr",
            "doc_id": "doc-7",
        }
    )
    rec = get_diagnostic_by_id(seq)
    assert rec is not None
    assert rec["doc_id"] == "doc-7"


def test_export_endpoint_writes_durable_snapshot_creating_nested_directory(
    app_client: TestClient, tmp_path: Path
) -> None:
    """``POST /api/v1/diagnostics/export`` writes the ring buffer to a JSON
    snapshot, creating a nested output directory when needed."""
    from mbforge.foundation.logger import push_diagnostic

    push_diagnostic(
        {
            "level": "ERROR",
            "message": "pipeline stage failed",
            "category": "pipeline.runner",
            "error_code": "stage_error",
        }
    )

    out_dir = tmp_path / "does" / "not" / "exist"
    response = app_client.post(
        "/api/v1/diagnostics/export",
        json={"directory": str(out_dir), "limit": 100},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] >= 1
    assert body["path"]

    written = Path(body["path"])
    assert written.parent == out_dir
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert "exported_at" in payload
    assert "stats" in payload
    assert any(rec.get("category") == "pipeline.runner" for rec in payload["errors"])

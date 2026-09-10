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

from mbforge.utils.logger import (
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


def test_json_formatter_emits_single_line_with_trace_fields() -> None:
    formatter = JsonFormatter()
    token = set_trace(doc_id="doc-42")
    try:
        rendered = formatter.format(_log_record())
    finally:
        reset_trace(token)

    payload = json.loads(rendered)
    # Single-line JSON must carry the structured schema + trace correlation.
    assert payload["doc_id"] == "doc-42"
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "mbforge.test.trace"
    assert payload["message"] == "boom"


def test_set_trace_is_restored_after_reset() -> None:
    formatter = JsonFormatter()
    token = set_trace(doc_id="doc-1")
    try:
        assert json.loads(formatter.format(_log_record()))["doc_id"] == "doc-1"
    finally:
        reset_trace(token)
    assert json.loads(formatter.format(_log_record()))["doc_id"] is None


def test_push_diagnostic_preserves_trace_fields(tmp_path: Path) -> None:
    """push_diagnostic passes caller-supplied doc_id through."""
    from mbforge.utils.logger import get_diagnostic_by_id, push_diagnostic

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


def test_export_endpoint_writes_durable_json_snapshot(
    app_client: TestClient, tmp_path: Path
) -> None:
    from mbforge.utils.logger import push_diagnostic

    push_diagnostic(
        {
            "level": "ERROR",
            "message": "pipeline stage failed",
            "category": "pipeline.runner",
            "error_code": "stage_error",
        }
    )

    out_dir = tmp_path / "exports"
    response = app_client.post(
        "/api/v1/diagnostics/export",
        json={"directory": str(out_dir), "limit": 100},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] >= 1
    assert body["path"]

    written = Path(body["path"])
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert "exported_at" in payload
    assert "stats" in payload
    assert any(rec.get("category") == "pipeline.runner" for rec in payload["errors"])


def test_export_endpoint_creates_nested_output_directory(
    app_client: TestClient, tmp_path: Path
) -> None:
    nested = tmp_path / "does" / "not" / "exist"
    response = app_client.post(
        "/api/v1/diagnostics/export",
        json={"directory": str(nested)},
    )
    assert response.status_code == 200
    body = response.json()
    written = Path(body["path"])
    assert written.parent == nested
    assert written.is_file()

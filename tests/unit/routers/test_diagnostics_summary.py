"""Regression coverage for the Settings diagnostics center."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from mbforge.service.dto.readiness import (
    BlockingModelReadiness,
    DatabaseReadiness,
    LibraryReadiness,
    ModelGateReadiness,
    ModelReadiness,
    OCRReadiness,
)
from mbforge.service.use_cases.system import readiness as readiness_service


def test_diagnostics_summary_returns_degraded_subsystems(
    app_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        readiness_service,
        "_probe_library_sync",
        lambda: LibraryReadiness(configured=False),
    )
    monkeypatch.setattr(
        readiness_service,
        "_probe_database_sync",
        lambda _library: DatabaseReadiness(ok=False, error="library_not_configured"),
    )
    monkeypatch.setattr(
        readiness_service,
        "_probe_models_sync",
        lambda: [
            ModelReadiness(
                id="moldet",
                name="MolDetv2-FT",
                status="error",
                expected_size_mb=640,
                cache_dir="C:/cache",
                last_error="download failed",
            )
        ],
    )
    monkeypatch.setattr(
        readiness_service,
        "_probe_layout_sync",
        lambda: OCRReadiness(chain=[], error="layout weights missing"),
    )
    monkeypatch.setattr(
        readiness_service,
        "_probe_model_gate_sync",
        lambda: ModelGateReadiness(
            ready=False,
            required=["moldet", "molparser"],
            missing=[
                BlockingModelReadiness(
                    id="moldet", name="MolDetv2-FT", status="not_found"
                )
            ],
            reason="missing models: moldet (not_found)",
        ),
    )
    response = app_client.get("/api/v1/diagnostics/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["library"] == {
        "configured": False,
        "path": None,
        "exists": False,
        "writable": False,
        "error": None,
    }
    assert body["database"]["ok"] is False
    assert body["database"]["error"] == "library_not_configured"
    assert body["models"][0]["last_error"] == "download failed"
    assert body["models"][0]["expected_size_mb"] == 640.0
    assert body["ocr"]["error"] == "layout weights missing"
    assert body["model_gate"] == {
        "ready": False,
        "required": ["moldet", "molparser"],
        "missing": [
            {
                "id": "moldet",
                "name": "MolDetv2-FT",
                "status": "not_found",
                "error": None,
            }
        ],
        "reason": "missing models: moldet (not_found)",
    }
    assert "llm" not in body


def test_demo_pdf_is_sanitized_and_registered(
    tmp_path: Path,
) -> None:
    pdf_path, doc_id = readiness_service._write_demo_pdf(str(tmp_path))

    assert pdf_path.is_file()
    assert doc_id  # a real doc_id was generated
    with pymupdf.open(pdf_path) as document:
        text = "\n".join(page.get_text() for page in document)
    assert "Synthetic sample document" in text
    assert "caffeine C8H10N4O2" in text
    # The document is registered in the library registry.
    from mbforge.db.document_records import get

    record = get(str(tmp_path), doc_id)
    assert record is not None
    assert record["title"] == "Readiness Demo"

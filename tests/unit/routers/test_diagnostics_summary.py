"""Regression coverage for the Settings diagnostics center."""

from __future__ import annotations

from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from mbforge.models.readiness import (
    DatabaseReadiness,
    LibraryReadiness,
    ModelReadiness,
    OCRReadiness,
)
from mbforge.services.system import readiness as readiness_service
from mbforge.utils.config import AppConfig, LLMConfig


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
        "_probe_ocr_sync",
        lambda: OCRReadiness(chain=[], error="ocr unavailable"),
    )
    monkeypatch.setattr(
        readiness_service,
        "_load_config_safe",
        lambda: AppConfig(
            llm=LLMConfig(provider="openai", model="gpt-test", api_key="")
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
    assert body["ocr"]["error"] == "ocr unavailable"
    assert body["llm"]["configured"] is False
    assert body["llm"]["has_api_key"] is False
    assert body["llm"]["base_url"] == "https://api.openai.com/v1"


def test_diagnostics_probe_llm_reports_missing_credentials(
    app_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        readiness_service,
        "_load_config_safe",
        lambda: AppConfig(
            llm=LLMConfig(provider="openai", model="gpt-test", api_key="")
        ),
    )

    response = app_client.post("/api/v1/diagnostics/probe-llm")

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "latency_ms": None,
        "error": "not_configured",
        "provider": "openai",
        "model": "gpt-test",
    }


def test_demo_pdf_is_sanitized_and_registered(
    tmp_path: Path,
) -> None:
    pdf_path, doc_id = readiness_service._write_demo_pdf(str(tmp_path))

    assert pdf_path.is_file()
    assert doc_id  # a real doc_id was generated
    with fitz.open(pdf_path) as document:
        text = "\n".join(page.get_text() for page in document)
    assert "Synthetic sample document" in text
    assert "caffeine C8H10N4O2" in text
    # The document is registered in library storage.
    from mbforge.storage.document_store import load_document

    doc = load_document(doc_id, str(tmp_path))
    assert doc is not None
    assert doc.title == "Readiness Demo"

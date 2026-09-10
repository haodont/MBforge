"""Pydantic models for the readiness diagnostics endpoints.

These schemas expose the health of the library root, SQLite database,
downloadable models, LLM provider, and OCR fallback chain.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LibraryReadiness(BaseModel):
    """Readiness of the configured library root directory."""

    configured: bool = False
    path: str | None = None
    exists: bool = False
    writable: bool = False
    error: str | None = None


class DatabaseReadiness(BaseModel):
    """Readiness of the library SQLite database."""

    ok: bool = False
    error: str | None = None


class ModelReadiness(BaseModel):
    """Readiness of a single downloadable model resource."""

    id: str
    name: str
    status: str
    local_path: str | None = None
    size_mb: float | None = None
    expected_size_mb: float | None = None
    cache_dir: str | None = None
    last_error: str | None = None


class LLMReadiness(BaseModel):
    """Readiness of the configured LLM provider (never leaks the API key)."""

    configured: bool = False
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    has_api_key: bool = False


class OCRReadiness(BaseModel):
    """Readiness of the OCR fallback chain."""

    chain: list[str] = Field(default_factory=list)
    error: str | None = None


class ReadinessSummaryResponse(BaseModel):
    """Aggregated read-only readiness summary."""

    library: LibraryReadiness
    database: DatabaseReadiness
    models: list[ModelReadiness] = Field(default_factory=list)
    llm: LLMReadiness
    ocr: OCRReadiness


class LLMProbeResponse(BaseModel):
    """Result of a live LLM probe request."""

    ok: bool = False
    latency_ms: int | None = None
    error: str | None = None
    provider: str = ""
    model: str = ""


class DemoRunResponse(BaseModel):
    """Result of enqueueing a generated demo PDF through the pipeline."""

    ok: bool = False
    task_id: str | None = None
    file_path: str = ""
    doc_id: str | None = None
    error: str | None = None

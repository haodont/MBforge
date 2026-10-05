"""Pydantic models for the readiness diagnostics endpoints.

These schemas expose the health of the library root, SQLite database,
downloadable models, and the local layout model.
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


class OCRReadiness(BaseModel):
    """Readiness of the local page-layout/text producer."""

    chain: list[str] = Field(default_factory=list)
    error: str | None = None


class BlockingModelReadiness(BaseModel):
    """A required model that is currently blocking queue claiming."""

    id: str
    name: str
    status: str
    error: str | None = None


class ModelGateReadiness(BaseModel):
    """Whether the ingest queue may claim documents, and why not."""

    ready: bool = False
    required: list[str] = Field(default_factory=list)
    missing: list[BlockingModelReadiness] = Field(default_factory=list)
    reason: str | None = None


class ReadinessSummaryResponse(BaseModel):
    """Aggregated read-only readiness summary."""

    library: LibraryReadiness
    database: DatabaseReadiness
    models: list[ModelReadiness] = Field(default_factory=list)
    ocr: OCRReadiness
    model_gate: ModelGateReadiness = Field(default_factory=ModelGateReadiness)


class DemoRunResponse(BaseModel):
    """Result of enqueueing a generated demo PDF through the pipeline."""

    ok: bool = False
    run_id: str | None = None
    file_path: str = ""
    doc_id: str | None = None
    error: str | None = None

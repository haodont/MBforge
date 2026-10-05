"""Pydantic models for the document endpoints.

Schemas for listing, deleting, and re-ingesting documents in the
MBForge library.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentListRequest(BaseModel):
    """Request body for listing documents."""

    library_root: str | None = Field(
        default=None,
        description="Library root path. Falls back to global config when omitted.",
    )


class DocumentListResponse(BaseModel):
    """Response body for listing documents."""

    success: bool = True
    documents: list[dict] = Field(default_factory=list)


class DocumentDeleteRequest(BaseModel):
    """Request body for deleting one or more documents in a single call."""

    library_root: str | None = Field(
        default=None,
        description="Library root path. Falls back to global config when omitted.",
    )
    doc_ids: list[str] = Field(
        default_factory=list,
        min_length=1,
        description="Document identifiers to delete.",
    )


class DocumentDeleteResponse(BaseModel):
    """Response body for deleting documents."""

    success: bool = True
    deleted: int = 0


class DocumentReingestRequest(BaseModel):
    """Request body for re-ingesting a document."""

    library_root: str | None = Field(
        default=None,
        description="Library root path. Falls back to global config when omitted.",
    )
    doc_id: str = Field(default="", description="Document identifier to re-ingest.")


class DocumentReingestResponse(BaseModel):
    """Response body for re-ingesting a document."""

    success: bool = True
    run_id: str | None = Field(default=None, description="Queued run ID.")
    message: str = "document queued for re-ingest"

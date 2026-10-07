"""Molecule query contract shared with the persistence layer.

``MoleculeRepository.list_page`` consumes this request, so it must live below
``service`` (the API DTO module re-exports it for its callers).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MoleculeListRequest(BaseModel):
    library_root: str = Field(..., description="Project root directory")
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(50, ge=1, le=10000, description="Items per page")
    status: str = Field("", description="Filter by status")
    source_type: str = Field("", description="Filter by source type")
    source_doc: str = Field("", description="Filter by source document")
    activity_presence: str = Field("all", description="Filter by activity presence")
    activity_min: float | None = Field(None, description="Minimum activity")
    activity_max: float | None = Field(None, description="Maximum activity")
    query: str = Field("", description="Text search query")
    sort_field: str = Field("created_at", description="Sort field")
    sort_direction: str = Field("desc", description="Sort direction")


__all__ = ["MoleculeListRequest"]

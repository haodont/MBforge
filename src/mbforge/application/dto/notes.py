"""Pydantic models for the notes router.

Schemas for creating, reading, updating, and deleting Markdown notes
linked to documents and entities in the MBForge library.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from mbforge.application.dto.common import LibraryRootMixin as _LibraryRootMixin


class NoteModel(BaseModel):
    """Full note payload used by ``POST /api/v1/notes/save``."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., min_length=1, description="Note identifier")
    title: str = Field(default="", description="Note title")
    content: str = Field(default="", description="Markdown content")
    tags: list[str] = Field(default_factory=list, description="Tag list")
    links: list[dict] = Field(
        default_factory=list, description="Outgoing links to entities"
    )
    created_at: str = Field(
        default="",
        alias="createdAt",
        description="Creation timestamp",
    )
    updated_at: str = Field(
        default="",
        alias="updatedAt",
        description="Last update timestamp",
    )


class NoteEntry(BaseModel):
    """Note metadata entry stored in the index and returned by list endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Note identifier")
    title: str = Field(default="", description="Note title")
    tags: list[str] = Field(default_factory=list, description="Tag list")
    links: list[dict] = Field(default_factory=list, description="Outgoing links")
    created_at: str = Field(
        default="",
        alias="createdAt",
        description="Creation timestamp",
    )
    updated_at: str = Field(
        default="",
        alias="updatedAt",
        description="Last update timestamp",
    )


class NotesListRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/notes/list``."""


class NotesListResponse(BaseModel):
    """Response body for ``POST /api/v1/notes/list``."""

    success: bool = True
    notes: list[NoteEntry] = Field(default_factory=list)


class NotesGetRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/notes/get``."""

    note_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("id", "doc_id"),
        description="Note identifier",
    )


class NotesGetResponse(BaseModel):
    """Response body for ``POST /api/v1/notes/get``."""

    success: bool = True
    notes: str = ""


class NotesSaveRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/notes/save``."""

    note: NoteModel = Field(..., description="Note to save")


class NotesSaveResponse(BaseModel):
    """Response body for ``POST /api/v1/notes/save``."""

    success: bool = True
    note: NoteEntry


class NotesDeleteRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/notes/delete``."""

    note_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("id", "doc_id"),
        description="Note identifier",
    )


class NotesDeleteResponse(BaseModel):
    """Response body for ``POST /api/v1/notes/delete``."""

    success: bool = True


class NotesBacklinksRequest(_LibraryRootMixin):
    """Request body for ``POST /api/v1/notes/backlinks``."""

    target_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("targetId", "target_id"),
        description="Target note identifier",
    )


class NotesBacklinksResponse(BaseModel):
    """Response body for ``POST /api/v1/notes/backlinks``."""

    success: bool = True
    backlinks: list[NoteEntry] = Field(default_factory=list)

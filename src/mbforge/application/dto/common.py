"""Common Pydantic response models.

Shared envelopes for success, error, and paginated responses, plus
utility schemas reused across multiple MBForge routers.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class LibraryRootMixin(BaseModel):
    """Accepts both ``library_root`` and ``libraryRoot``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    library_root: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("library_root", "libraryRoot"),
        description="Library root for the request",
    )


class SuccessResponse(BaseModel):
    success: bool = True
    message: str = ""


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    error_code: str = "internal_error"


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int = 1
    page_size: int = 50


class ModelTestRequest(BaseModel):
    model_id: str
    subpath: str | None = None


class ModelTestResponse(BaseModel):
    success: bool = True
    ok: bool = False
    error: str = ""
    duration_ms: int = 0


class MoleculeRenderRequest(BaseModel):
    smiles: str
    width: int | None = 300
    height: int | None = 200


class MoleculeRenderResponse(BaseModel):
    success: bool = False
    image_base64: str | None = None
    error: str = ""

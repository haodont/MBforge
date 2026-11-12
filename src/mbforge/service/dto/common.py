"""Common Pydantic response models.

Utility schemas reused across multiple MBForge routers.
"""

from __future__ import annotations

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

"""Page-frame DTO shared by the Extract producer and its SQL readers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _EvidenceArtifactModel(BaseModel):
    """Strict models for the page-evidence boundary."""

    model_config = ConfigDict(extra="forbid")


class PageFrame(_EvidenceArtifactModel):
    """One visual PDF page frame."""

    page: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: int = 0


__all__ = ["PageFrame"]

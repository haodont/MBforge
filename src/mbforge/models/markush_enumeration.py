"""Pydantic models for the Markush enumeration API.

Wire-format mirror of the types in :mod:`mbforge.core.enumeration`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SelectionOrigin = Literal["text_definition", "proximity", "manual"]


class EnumerationSiteSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_label: str
    atom_map_num: int
    fragments: list[str] = Field(default_factory=list)


class EnumerationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    scaffold_id: str
    selection: list[EnumerationSiteSelection] = Field(default_factory=list)
    requested_limit: int = Field(default=500, ge=1, le=10_000)


class EnumerationPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theoretical_count: int
    requested_limit: int
    truncated: bool


class EnumerationRunRequest(EnumerationPreviewRequest):
    # Same fields; we re-declare to keep types distinct in OpenAPI.
    pass


class EnumerationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    theoretical_count: int
    written_count: int
    truncated: bool
    status: str
    error: str | None = None


class EnumerationResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_id: str
    smiles: str
    canonical_smiles: str
    combination_key: str
    assignments: list[dict] = Field(default_factory=list)
    validation_status: str
    review_status: str


class EnumerationResultsRequest(BaseModel):
    """List generated candidates for a run."""

    library_root: str | None = None
    run_id: str = ""


class EnumerationResultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EnumerationResultItem] = Field(default_factory=list)


class GeneratedDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    entity_id: str
    action: Literal["confirm", "reject"]
    reason: str = ""

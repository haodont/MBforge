"""Pydantic models for Markush attachment sites, options, and mounts.

These types describe the relational shape between a scaffold and its
R-groups:

- ``MarkushSite`` records an explicit attachment point on a scaffold.
  ``site_label`` is the human-readable name (R1, R2, …) and
  ``atom_map_num`` is the integer map-number embedded in the scaffold
  SMILES via ``[*:1]``-style notation. Sites without an atom map are
  rejected by the service layer.
- ``MarkushOption`` records the candidates bound to a site: either a
  concrete ``fragment_id`` or a free-form ``normalized_smiles`` paired
  with a textual ``definition_text``.
- ``MarkushMount`` records the (site, fragment) binding with an origin
  (text_definition / proximity / manual) and a confidence score.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SiteStatus = Literal["pending", "confirmed", "rejected"]
OptionStatus = Literal["pending", "confirmed", "rejected"]
MountStatus = Literal["suggested", "confirmed", "rejected"]
MountOrigin = Literal["text_definition", "proximity", "manual"]


class MarkushSite(BaseModel):
    """One explicit attachment point on a scaffold."""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    scaffold_id: str
    site_label: str
    atom_map_num: int | None = None
    attachment_count: int = 1
    bond_type: str | None = None
    source_text: str = ""
    status: SiteStatus = "pending"
    properties: dict[str, str] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class MarkushSiteListRequest(BaseModel):
    """List-sites payload."""

    library_root: str | None = None
    scaffold_id: str = ""


class MarkushOptionListRequest(BaseModel):
    """List-options payload."""

    library_root: str | None = None
    site_id: str = ""


class MarkushMountListRequest(BaseModel):
    """List-mounts payload (all filters optional)."""

    library_root: str | None = None
    site_id: str | None = None
    scaffold_id: str | None = None
    fragment_id: str | None = None


class MarkushSiteCreate(BaseModel):
    """Create-site payload."""

    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    scaffold_id: str
    site_label: str
    atom_map_num: int | None = None
    attachment_count: int = Field(default=1, ge=1)
    bond_type: str | None = None
    source_text: str = ""


class MarkushSiteUpdate(BaseModel):
    """Edit-site payload."""

    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    site_id: str
    site_label: str | None = None
    atom_map_num: int | None = None
    attachment_count: int | None = Field(default=None, ge=1)
    bond_type: str | None = None
    source_text: str | None = None


class MarkushOption(BaseModel):
    """One R-group candidate bound to a site."""

    model_config = ConfigDict(extra="forbid")

    option_id: str
    site_id: str
    fragment_id: str | None = None
    normalized_smiles: str | None = None
    definition_text: str = ""
    constraints: dict[str, str] = Field(default_factory=dict)
    status: OptionStatus = "pending"
    created_at: str | None = None
    updated_at: str | None = None


class MarkushOptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    site_id: str
    fragment_id: str | None = None
    normalized_smiles: str | None = None
    definition_text: str = ""
    constraints: dict[str, str] = Field(default_factory=dict)


class MarkushMount(BaseModel):
    """A (site, fragment) mount with origin and confidence."""

    model_config = ConfigDict(extra="forbid")

    mount_id: str
    site_id: str
    fragment_id: str
    origin: MountOrigin
    confidence: float | None = None
    reasons: list[str] = Field(default_factory=list)
    status: MountStatus = "suggested"
    created_at: str | None = None
    updated_at: str | None = None


class MarkushMountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    site_id: str
    fragment_id: str
    origin: MountOrigin = "manual"
    confidence: float | None = None
    reasons: list[str] = Field(default_factory=list)


class MarkushMountDecision(BaseModel):
    """Confirm / reject an existing mount."""

    model_config = ConfigDict(extra="forbid")

    library_root: str | None = None
    mount_id: str
    action: Literal["confirm", "reject"]
    reason: str = ""


class MarkushSiteListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MarkushSite] = Field(default_factory=list)


class MarkushOptionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MarkushOption] = Field(default_factory=list)


class MarkushMountListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MarkushMount] = Field(default_factory=list)

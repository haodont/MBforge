"""Shared router-side helpers for the Markush router subpackage.

Repository resolution (routers must not open a raw database connection) and
request-shaping helpers shared by the sub-routers live here.
"""

from __future__ import annotations

from fastapi import APIRouter

from mbforge.foundation.errors import ValidationError
from mbforge.service.ports import LibraryRepositories, get_repositories

router = APIRouter()  # placeholder; sub-routers reuse the type only


def resolve_repositories(library_root: str | None) -> LibraryRepositories:
    """Return the repositories for *library_root* (required by the API)."""
    if not library_root:
        raise ValidationError("library_root is required")
    return get_repositories(library_root)


def to_selections(items: list) -> list:
    """Map a Pydantic selection list to the internal ``SiteSelection`` objects."""
    from mbforge.domain.enumeration import SiteSelection

    return [
        SiteSelection(
            site_label=i.site_label,
            atom_map_num=i.atom_map_num,
            fragments=list(i.fragments),
        )
        for i in items
    ]

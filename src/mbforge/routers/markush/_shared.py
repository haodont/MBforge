"""Shared router-side helpers for the Markush router subpackage.

DB-handle resolution lives in :mod:`mbforge.services.markush._db`
(routers must not import DatabaseManager); this module keeps only
request-shaping helpers shared by the sub-routers.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()  # placeholder; sub-routers reuse the type only


def to_selections(items: list) -> list:
    """Map a Pydantic selection list to the internal ``SiteSelection`` objects."""
    from ...core.enumeration import SiteSelection

    return [
        SiteSelection(
            site_label=i.site_label,
            atom_map_num=i.atom_map_num,
            fragments=list(i.fragments),
        )
        for i in items
    ]

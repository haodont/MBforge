"""Service layer for Markush attachment sites, options, and mounts.

This module sits on top of the ``markush_sites`` / ``markush_options`` /
``markush_mounts`` database schema and exposes the operations the HTTP
router and the review UI need. The SQL now lives behind
:class:`~mbforge.ports.repositories.MarkushRepository`; the error type comes
from :mod:`mbforge.domain.markush`.

Invariants enforced by the operations below:

- ``MarkushSite`` rows require an explicit ``atom_map_num``; implicit
  mapping by ``*`` position order is disallowed.
- A fragment with N attachment points can only be mounted on sites
  whose ``attachment_count`` matches; mismatches are rejected.
- ``MarkushMount`` rows are scoped per ``(site_id, fragment_id)`` so
  the same fragment can legitimately serve multiple scaffolds / sites.
- All mutations append a ``markush_decisions`` audit row so the review
  trail covers site edits, option edits, and mount decisions.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from mbforge.domain.markush import MarkushSiteError
from mbforge.foundation.files import safe_json_loads
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger
from mbforge.ports.repositories import MarkushRepository
from mbforge.service.dto.markush_sites import (
    MarkushMount,
    MarkushOption,
    MarkushSite,
)

logger = get_logger("mbforge.service.use_cases.markush.sites")


def _fragment_attachment_count(
    repository: MarkushRepository, fragment_id: str
) -> int | None:
    """Return the attachment count of a stored fragment by ``*`` count in SMILES.

    Returns ``None`` when the fragment does not exist; raises
    :class:`MarkushSiteError` when the fragment's attachment count cannot
    be parsed.
    """
    smiles = repository.fragment_smiles(fragment_id)
    if smiles is None:
        return None
    return smiles.count("*")


def _row_to_site(row: dict[str, Any]) -> MarkushSite:
    properties = safe_json_loads(row["properties"], {})
    return MarkushSite(
        site_id=row["site_id"],
        scaffold_id=row["scaffold_id"],
        site_label=row["site_label"],
        atom_map_num=row["atom_map_num"],
        attachment_count=row["attachment_count"],
        bond_type=row["bond_type"],
        source_text=row["source_text"] or "",
        status=row["status"],
        properties=properties,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_option(row: dict[str, Any]) -> MarkushOption:
    constraints = safe_json_loads(row["constraints"], {})
    return MarkushOption(
        option_id=row["option_id"],
        site_id=row["site_id"],
        fragment_id=row["fragment_id"],
        normalized_smiles=row["normalized_smiles"],
        definition_text=row["definition_text"] or "",
        constraints=constraints,
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_mount(row: dict[str, Any]) -> MarkushMount:
    reasons = safe_json_loads(row["reasons"], [])
    return MarkushMount(
        mount_id=row["mount_id"],
        site_id=row["site_id"],
        fragment_id=row["fragment_id"],
        origin=row["origin"],
        confidence=row["confidence"],
        reasons=reasons,
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


def list_sites(repository: MarkushRepository, scaffold_id: str) -> list[MarkushSite]:
    return [_row_to_site(row) for row in repository.list_site_rows(scaffold_id)]


def create_site(
    repository: MarkushRepository,
    *,
    scaffold_id: str,
    site_label: str,
    atom_map_num: int | None = None,
    attachment_count: int = 1,
    bond_type: str | None = None,
    source_text: str = "",
) -> MarkushSite:
    """Insert a new attachment site with explicit atom-map validation.

    The scaffold must exist and its SMILES must contain enough ``*``
    atoms to host the requested atom-map number — this catches
    out-of-range mappings at write time rather than at render time.
    """
    if attachment_count < 1:
        raise MarkushSiteError("attachment_count must be >= 1")
    if atom_map_num is None:
        raise MarkushSiteError("atom_map_num is required")
    scaffold = repository.scaffold_site_context(scaffold_id)
    if scaffold is None:
        raise MarkushSiteError(f"scaffold not found: {scaffold_id}")
    if scaffold["status"] != "confirmed":
        raise MarkushSiteError(f"scaffold is not confirmed: {scaffold_id}")
    star_count = (scaffold["smiles"] or "").count("*")
    if atom_map_num < 1 or atom_map_num > star_count:
        raise MarkushSiteError(
            f"atom_map_num {atom_map_num} is out of range; "
            f"scaffold has {star_count} attachment points"
        )
    site_id = short_id()
    repository.insert_site(
        site_id=site_id,
        scaffold_id=scaffold_id,
        site_label=site_label,
        atom_map_num=atom_map_num,
        attachment_count=attachment_count,
        bond_type=bond_type,
        source_text=source_text,
    )
    created = repository.get_site_row(site_id)
    assert created is not None
    return _row_to_site(created)


def update_site(
    repository: MarkushRepository,
    *,
    site_id: str,
    site_label: str | None = None,
    atom_map_num: int | None = None,
    attachment_count: int | None = None,
    bond_type: str | None = None,
    source_text: str | None = None,
) -> MarkushSite:
    row = repository.get_site_row(site_id)
    if row is None:
        raise MarkushSiteError(f"site not found: {site_id}")
    if attachment_count is not None and attachment_count < 1:
        raise MarkushSiteError("attachment_count must be >= 1")
    updated = repository.update_site_row(
        site_id=site_id,
        site_label=site_label,
        atom_map_num=atom_map_num,
        attachment_count=attachment_count,
        bond_type=bond_type,
        source_text=source_text,
    )
    assert updated is not None
    return _row_to_site(updated)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def list_options(repository: MarkushRepository, site_id: str) -> list[MarkushOption]:
    return [_row_to_option(row) for row in repository.list_option_rows(site_id)]


def create_option(
    repository: MarkushRepository,
    *,
    site_id: str,
    fragment_id: str | None = None,
    normalized_smiles: str | None = None,
    definition_text: str = "",
    constraints: dict[str, str] | None = None,
) -> MarkushOption:
    if fragment_id is None and not (normalized_smiles or definition_text):
        raise MarkushSiteError(
            "an option requires either fragment_id or one of "
            "(normalized_smiles, definition_text)"
        )
    site = repository.site_status(site_id)
    if site is None:
        raise MarkushSiteError(f"site not found: {site_id}")
    if fragment_id is not None:
        fragment = repository.fragment_status(fragment_id)
        if fragment is None:
            raise MarkushSiteError(f"fragment not found: {fragment_id}")
        if fragment["status"] != "confirmed":
            raise MarkushSiteError(f"fragment is not confirmed: {fragment_id}")
    option_id = short_id()
    repository.insert_option(
        option_id=option_id,
        site_id=site_id,
        fragment_id=fragment_id,
        normalized_smiles=normalized_smiles,
        definition_text=definition_text,
        constraints_json=json.dumps(constraints or {}, ensure_ascii=False),
    )
    created = repository.get_option_row(option_id)
    assert created is not None
    return _row_to_option(created)


# ---------------------------------------------------------------------------
# Mounts
# ---------------------------------------------------------------------------


def list_mounts(
    repository: MarkushRepository,
    *,
    site_id: str | None = None,
    scaffold_id: str | None = None,
    fragment_id: str | None = None,
) -> list[MarkushMount]:
    rows = repository.list_mount_rows(
        site_id=site_id,
        scaffold_id=scaffold_id,
        fragment_id=fragment_id,
    )
    return [_row_to_mount(row) for row in rows]


def create_mount(
    repository: MarkushRepository,
    *,
    site_id: str,
    fragment_id: str,
    origin: str = "manual",
    confidence: float | None = None,
    reasons: Iterable[str] | None = None,
) -> MarkushMount:
    """Create a (site, fragment) mount with attachment-count compatibility check.

    A multi-attachment fragment cannot be mounted on a single-attachment
    site and vice versa; the check surfaces a clear error rather than
    silently producing a half-mounted structure.
    """
    site = repository.get_site_row(site_id)
    if site is None:
        raise MarkushSiteError(f"site not found: {site_id}")
    fragment_attachments = _fragment_attachment_count(repository, fragment_id)
    if fragment_attachments is None:
        raise MarkushSiteError(f"fragment not found: {fragment_id}")
    fragment_row = repository.fragment_status(fragment_id)
    if fragment_row is None or fragment_row["status"] != "confirmed":
        raise MarkushSiteError(f"fragment is not confirmed: {fragment_id}")
    if fragment_attachments != site["attachment_count"]:
        raise MarkushSiteError(
            f"attachment mismatch: site {site['site_label']} expects "
            f"{site['attachment_count']}, fragment has {fragment_attachments}"
        )
    # Idempotent: same (site, fragment) → reuse the existing row.
    existing = repository.find_mount_row(site_id, fragment_id)
    if existing is not None:
        return _row_to_mount(existing)
    mount_id = short_id()
    repository.insert_mount(
        mount_id=mount_id,
        site_id=site_id,
        fragment_id=fragment_id,
        origin=origin,
        confidence=confidence,
        reasons_json=json.dumps(list(reasons or []), ensure_ascii=False),
    )
    created = repository.get_mount_row(mount_id)
    assert created is not None
    return _row_to_mount(created)


def decide_mount(
    repository: MarkushRepository,
    *,
    mount_id: str,
    action: str,
    reason: str = "",
) -> MarkushMount:
    if action not in {"confirm", "reject"}:
        raise MarkushSiteError(f"unknown mount action: {action}")
    row = repository.get_mount_row(mount_id)
    if row is None:
        raise MarkushSiteError(f"mount not found: {mount_id}")
    if row["status"] != "suggested":
        raise MarkushSiteError(f"mount is already {row['status']}")
    if action == "confirm":
        fragment_row = repository.fragment_status(row["fragment_id"])
        if fragment_row is None or fragment_row["status"] != "confirmed":
            raise MarkushSiteError(f"fragment is not confirmed: {row['fragment_id']}")
    new_status = "confirmed" if action == "confirm" else "rejected"
    # Audit entry for the mount decision. ``markush_decisions.entity_type``
    # is the same string we use for the review queue; the snapshot keeps
    # the mount state at decision time. The status flip and the audit row
    # are written in one repository transaction.
    repository.apply_mount_decision(
        mount_id=mount_id,
        new_status=new_status,
        decision_id=short_id(),
        action=f"mount_{action}",
        previous_state=row["status"],
        reason=reason,
        snapshot_json=json.dumps(
            {"site_id": row["site_id"], "fragment_id": row["fragment_id"]},
            ensure_ascii=False,
        ),
    )
    updated = repository.get_mount_row(mount_id)
    assert updated is not None
    return _row_to_mount(updated)


__all__ = [
    "create_mount",
    "create_option",
    "create_site",
    "decide_mount",
    "list_mounts",
    "list_options",
    "list_sites",
    "update_site",
]

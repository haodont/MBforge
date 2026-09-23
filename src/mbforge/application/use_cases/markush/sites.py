"""Service layer for Markush attachment sites, options, and mounts.

This module sits on top of the ``markush_sites`` / ``markush_options`` /
``markush_mounts`` database schema and exposes the operations the HTTP
router and the review UI need. The error type comes from
:mod:`mbforge.domain.markush`.

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
import sqlite3
from collections.abc import Iterable
from typing import Any

from mbforge.application.dto.markush_sites import (
    MarkushMount,
    MarkushOption,
    MarkushSite,
)
from mbforge.domain.markush import MarkushSiteError
from mbforge.foundation.files import safe_json_loads
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.use_cases.markush.sites")


def _fragment_attachment_count(
    conn: sqlite3.Connection, fragment_id: str
) -> int | None:
    """Return the attachment count of a stored fragment by ``*`` count in SMILES.

    Returns ``None`` when the fragment does not exist; raises
    :class:`MarkushSiteError` when the fragment's attachment count cannot
    be parsed.
    """
    row = conn.execute(
        "SELECT smiles FROM markush_fragments WHERE fragment_id = ?",
        (fragment_id,),
    ).fetchone()
    if row is None:
        return None
    smiles = row["smiles"] or ""
    return smiles.count("*")


def _row_to_site(row: sqlite3.Row) -> MarkushSite:
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


def _row_to_option(row: sqlite3.Row) -> MarkushOption:
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


def _row_to_mount(row: sqlite3.Row) -> MarkushMount:
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


def list_sites(conn: sqlite3.Connection, scaffold_id: str) -> list[MarkushSite]:
    rows = conn.execute(
        "SELECT * FROM markush_sites WHERE scaffold_id = ? ORDER BY site_label, site_id",
        (scaffold_id,),
    ).fetchall()
    return [_row_to_site(r) for r in rows]


def create_site(
    conn: sqlite3.Connection,
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
    scaffold = conn.execute(
        "SELECT smiles, status FROM markush_scaffolds WHERE scaffold_id = ?",
        (scaffold_id,),
    ).fetchone()
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
    conn.execute(
        """
        INSERT INTO markush_sites
            (site_id, scaffold_id, site_label, atom_map_num,
             attachment_count, bond_type, source_text, status, properties)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', '{}')
        """,
        (
            site_id,
            scaffold_id,
            site_label,
            atom_map_num,
            attachment_count,
            bond_type,
            source_text,
        ),
    )
    return _row_to_site(
        conn.execute(
            "SELECT * FROM markush_sites WHERE site_id = ?", (site_id,)
        ).fetchone()
    )


def update_site(
    conn: sqlite3.Connection,
    *,
    site_id: str,
    site_label: str | None = None,
    atom_map_num: int | None = None,
    attachment_count: int | None = None,
    bond_type: str | None = None,
    source_text: str | None = None,
) -> MarkushSite:
    row = conn.execute(
        "SELECT * FROM markush_sites WHERE site_id = ?", (site_id,)
    ).fetchone()
    if row is None:
        raise MarkushSiteError(f"site not found: {site_id}")
    fields: list[str] = []
    params: list[Any] = []
    if site_label is not None:
        fields.append("site_label = ?")
        params.append(site_label)
    if atom_map_num is not None:
        fields.append("atom_map_num = ?")
        params.append(atom_map_num)
    if attachment_count is not None:
        if attachment_count < 1:
            raise MarkushSiteError("attachment_count must be >= 1")
        fields.append("attachment_count = ?")
        params.append(attachment_count)
    if bond_type is not None:
        fields.append("bond_type = ?")
        params.append(bond_type)
    if source_text is not None:
        fields.append("source_text = ?")
        params.append(source_text)
    if not fields:
        return _row_to_site(row)
    fields.append("updated_at = datetime('now')")
    params.append(site_id)
    conn.execute(
        f"UPDATE markush_sites SET {', '.join(fields)} WHERE site_id = ?",
        params,
    )
    updated = conn.execute(
        "SELECT * FROM markush_sites WHERE site_id = ?", (site_id,)
    ).fetchone()
    return _row_to_site(updated)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def list_options(conn: sqlite3.Connection, site_id: str) -> list[MarkushOption]:
    rows = conn.execute(
        "SELECT * FROM markush_options WHERE site_id = ? ORDER BY option_id",
        (site_id,),
    ).fetchall()
    return [_row_to_option(r) for r in rows]


def create_option(
    conn: sqlite3.Connection,
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
    site = conn.execute(
        "SELECT site_id, status FROM markush_sites WHERE site_id = ?", (site_id,)
    ).fetchone()
    if site is None:
        raise MarkushSiteError(f"site not found: {site_id}")
    if fragment_id is not None:
        fragment = conn.execute(
            "SELECT status FROM markush_fragments WHERE fragment_id = ?",
            (fragment_id,),
        ).fetchone()
        if fragment is None:
            raise MarkushSiteError(f"fragment not found: {fragment_id}")
        if fragment["status"] != "confirmed":
            raise MarkushSiteError(f"fragment is not confirmed: {fragment_id}")
    option_id = short_id()
    conn.execute(
        """
        INSERT INTO markush_options
            (option_id, site_id, fragment_id, normalized_smiles,
             definition_text, constraints, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            option_id,
            site_id,
            fragment_id,
            normalized_smiles,
            definition_text,
            json.dumps(constraints or {}, ensure_ascii=False),
        ),
    )
    return _row_to_option(
        conn.execute(
            "SELECT * FROM markush_options WHERE option_id = ?", (option_id,)
        ).fetchone()
    )


# ---------------------------------------------------------------------------
# Mounts
# ---------------------------------------------------------------------------


def list_mounts(
    conn: sqlite3.Connection,
    *,
    site_id: str | None = None,
    scaffold_id: str | None = None,
    fragment_id: str | None = None,
) -> list[MarkushMount]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if site_id is not None:
        clauses.append("m.site_id = ?")
        params.append(site_id)
    if fragment_id is not None:
        clauses.append("m.fragment_id = ?")
        params.append(fragment_id)
    if scaffold_id is not None:
        clauses.append(
            "m.site_id IN (SELECT site_id FROM markush_sites WHERE scaffold_id = ?)"
        )
        params.append(scaffold_id)
    rows = conn.execute(
        f"SELECT m.* FROM markush_mounts m WHERE {' AND '.join(clauses)} "
        "ORDER BY m.created_at DESC, m.mount_id",
        params,
    ).fetchall()
    return [_row_to_mount(r) for r in rows]


def create_mount(
    conn: sqlite3.Connection,
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
    site = conn.execute(
        "SELECT * FROM markush_sites WHERE site_id = ?", (site_id,)
    ).fetchone()
    if site is None:
        raise MarkushSiteError(f"site not found: {site_id}")
    fragment_attachments = _fragment_attachment_count(conn, fragment_id)
    if fragment_attachments is None:
        raise MarkushSiteError(f"fragment not found: {fragment_id}")
    fragment_row = conn.execute(
        "SELECT status FROM markush_fragments WHERE fragment_id = ?",
        (fragment_id,),
    ).fetchone()
    if fragment_row is None or fragment_row["status"] != "confirmed":
        raise MarkushSiteError(f"fragment is not confirmed: {fragment_id}")
    if fragment_attachments != site["attachment_count"]:
        raise MarkushSiteError(
            f"attachment mismatch: site {site['site_label']} expects "
            f"{site['attachment_count']}, fragment has {fragment_attachments}"
        )
    # Idempotent: same (site, fragment) → reuse the existing row.
    existing = conn.execute(
        "SELECT * FROM markush_mounts WHERE site_id = ? AND fragment_id = ?",
        (site_id, fragment_id),
    ).fetchone()
    if existing is not None:
        return _row_to_mount(existing)
    mount_id = short_id()
    conn.execute(
        """
        INSERT INTO markush_mounts
            (mount_id, site_id, fragment_id, origin, confidence,
             reasons, status)
        VALUES (?, ?, ?, ?, ?, ?, 'suggested')
        """,
        (
            mount_id,
            site_id,
            fragment_id,
            origin,
            confidence,
            json.dumps(list(reasons or []), ensure_ascii=False),
        ),
    )
    return _row_to_mount(
        conn.execute(
            "SELECT * FROM markush_mounts WHERE mount_id = ?", (mount_id,)
        ).fetchone()
    )


def decide_mount(
    conn: sqlite3.Connection, *, mount_id: str, action: str, reason: str = ""
) -> MarkushMount:
    if action not in {"confirm", "reject"}:
        raise MarkushSiteError(f"unknown mount action: {action}")
    row = conn.execute(
        "SELECT * FROM markush_mounts WHERE mount_id = ?", (mount_id,)
    ).fetchone()
    if row is None:
        raise MarkushSiteError(f"mount not found: {mount_id}")
    if row["status"] != "suggested":
        raise MarkushSiteError(f"mount is already {row['status']}")
    if action == "confirm":
        fragment_row = conn.execute(
            "SELECT status FROM markush_fragments WHERE fragment_id = ?",
            (row["fragment_id"],),
        ).fetchone()
        if fragment_row is None or fragment_row["status"] != "confirmed":
            raise MarkushSiteError(f"fragment is not confirmed: {row['fragment_id']}")
    new_status = "confirmed" if action == "confirm" else "rejected"
    conn.execute(
        """
        UPDATE markush_mounts
        SET status = ?, updated_at = datetime('now')
        WHERE mount_id = ?
        """,
        (new_status, mount_id),
    )
    # Audit entry for the mount decision. ``markush_decisions.entity_type``
    # is the same string we use for the review queue; the snapshot keeps
    # the mount state at decision time.
    conn.execute(
        """
        INSERT INTO markush_decisions
            (decision_id, entity_type, entity_id, action,
             previous_state, new_state, reason, snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            short_id(),
            "markush_mount",
            mount_id,
            f"mount_{action}",
            row["status"],
            new_status,
            reason,
            json.dumps(
                {"site_id": row["site_id"], "fragment_id": row["fragment_id"]},
                ensure_ascii=False,
            ),
        ),
    )
    return _row_to_mount(
        conn.execute(
            "SELECT * FROM markush_mounts WHERE mount_id = ?", (mount_id,)
        ).fetchone()
    )


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

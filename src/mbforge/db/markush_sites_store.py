"""SQLite data access for Markush attachment sites, options, and mounts.

Owns every query the Markush site/option/mount use cases need so the service
layer never executes SQL. Functions take a caller-owned ``sqlite3.Connection``
and return raw row dicts; the service layer converts them to DTOs and raises
the domain errors.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def _one(conn: sqlite3.Connection, sql: str, params: Any) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


def scaffold_site_context(
    conn: sqlite3.Connection, scaffold_id: str
) -> dict[str, Any] | None:
    """Return the ``smiles``/``status`` of a scaffold, or ``None``."""
    return _one(
        conn,
        "SELECT smiles, status FROM markush_scaffolds WHERE scaffold_id = ?",
        (scaffold_id,),
    )


def insert_site(
    conn: sqlite3.Connection,
    *,
    site_id: str,
    scaffold_id: str,
    site_label: str,
    atom_map_num: int,
    attachment_count: int,
    bond_type: str | None,
    source_text: str,
) -> None:
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


def get_site_row(conn: sqlite3.Connection, site_id: str) -> dict[str, Any] | None:
    return _one(conn, "SELECT * FROM markush_sites WHERE site_id = ?", (site_id,))


def list_site_rows(conn: sqlite3.Connection, scaffold_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM markush_sites WHERE scaffold_id = ? ORDER BY site_label, site_id",
        (scaffold_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_site_row(
    conn: sqlite3.Connection,
    *,
    site_id: str,
    site_label: str | None,
    atom_map_num: int | None,
    attachment_count: int | None,
    bond_type: str | None,
    source_text: str | None,
) -> dict[str, Any] | None:
    """Update the provided site fields and return the fresh row.

    ``None`` means "leave unchanged"; when nothing is provided the existing row
    is returned untouched.
    """
    fields: list[str] = []
    params: list[Any] = []
    if site_label is not None:
        fields.append("site_label = ?")
        params.append(site_label)
    if atom_map_num is not None:
        fields.append("atom_map_num = ?")
        params.append(atom_map_num)
    if attachment_count is not None:
        fields.append("attachment_count = ?")
        params.append(attachment_count)
    if bond_type is not None:
        fields.append("bond_type = ?")
        params.append(bond_type)
    if source_text is not None:
        fields.append("source_text = ?")
        params.append(source_text)
    if not fields:
        return get_site_row(conn, site_id)
    fields.append("updated_at = datetime('now')")
    params.append(site_id)
    conn.execute(
        f"UPDATE markush_sites SET {', '.join(fields)} WHERE site_id = ?",
        params,
    )
    return get_site_row(conn, site_id)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def site_status(conn: sqlite3.Connection, site_id: str) -> dict[str, Any] | None:
    return _one(
        conn,
        "SELECT site_id, status FROM markush_sites WHERE site_id = ?",
        (site_id,),
    )


def fragment_status(
    conn: sqlite3.Connection, fragment_id: str
) -> dict[str, Any] | None:
    return _one(
        conn,
        "SELECT status FROM markush_fragments WHERE fragment_id = ?",
        (fragment_id,),
    )


def fragment_smiles(conn: sqlite3.Connection, fragment_id: str) -> str | None:
    row = conn.execute(
        "SELECT smiles FROM markush_fragments WHERE fragment_id = ?",
        (fragment_id,),
    ).fetchone()
    return (row["smiles"] or "") if row is not None else None


def insert_option(
    conn: sqlite3.Connection,
    *,
    option_id: str,
    site_id: str,
    fragment_id: str | None,
    normalized_smiles: str | None,
    definition_text: str,
    constraints_json: str,
) -> None:
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
            constraints_json,
        ),
    )


def get_option_row(conn: sqlite3.Connection, option_id: str) -> dict[str, Any] | None:
    return _one(conn, "SELECT * FROM markush_options WHERE option_id = ?", (option_id,))


def list_option_rows(conn: sqlite3.Connection, site_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM markush_options WHERE site_id = ? ORDER BY option_id",
        (site_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Mounts
# ---------------------------------------------------------------------------


def list_mount_rows(
    conn: sqlite3.Connection,
    *,
    site_id: str | None = None,
    scaffold_id: str | None = None,
    fragment_id: str | None = None,
) -> list[dict[str, Any]]:
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
    return [dict(row) for row in rows]


def find_mount_row(
    conn: sqlite3.Connection, site_id: str, fragment_id: str
) -> dict[str, Any] | None:
    return _one(
        conn,
        "SELECT * FROM markush_mounts WHERE site_id = ? AND fragment_id = ?",
        (site_id, fragment_id),
    )


def get_mount_row(conn: sqlite3.Connection, mount_id: str) -> dict[str, Any] | None:
    return _one(conn, "SELECT * FROM markush_mounts WHERE mount_id = ?", (mount_id,))


def insert_mount(
    conn: sqlite3.Connection,
    *,
    mount_id: str,
    site_id: str,
    fragment_id: str,
    origin: str,
    confidence: float | None,
    reasons_json: str,
) -> None:
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
            reasons_json,
        ),
    )


def apply_mount_decision(
    conn: sqlite3.Connection,
    *,
    mount_id: str,
    new_status: str,
    decision_id: str,
    action: str,
    previous_state: str | None,
    reason: str,
    snapshot_json: str,
) -> None:
    """Flip a mount's status and append its audit row in one transaction."""
    conn.execute(
        """
        UPDATE markush_mounts
        SET status = ?, updated_at = datetime('now')
        WHERE mount_id = ?
        """,
        (new_status, mount_id),
    )
    conn.execute(
        """
        INSERT INTO markush_decisions
            (decision_id, entity_type, entity_id, action,
             previous_state, new_state, reason, snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            "markush_mount",
            mount_id,
            action,
            previous_state,
            new_status,
            reason,
            snapshot_json,
        ),
    )


__all__ = [
    "apply_mount_decision",
    "find_mount_row",
    "fragment_smiles",
    "fragment_status",
    "get_mount_row",
    "get_option_row",
    "get_site_row",
    "insert_mount",
    "insert_option",
    "insert_site",
    "list_mount_rows",
    "list_option_rows",
    "list_site_rows",
    "scaffold_site_context",
    "site_status",
    "update_site_row",
]

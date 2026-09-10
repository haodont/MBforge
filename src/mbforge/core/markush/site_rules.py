"""Validation rules for Markush attachment-site operations.

Owns the error type and the fragment attachment-count rule shared by
the site/option/mount persistence operations in
:mod:`mbforge.services.markush.sites`.

Invariants enforced here (checked by the service layer):

- ``MarkushSite`` rows require an explicit ``atom_map_num``; implicit
  mapping by ``*`` position order is disallowed.
- A fragment with N attachment points can only be mounted on sites
  whose ``attachment_count`` matches; mismatches are rejected.
"""

from __future__ import annotations

import sqlite3

from ...utils.errors import MBForgeError


class MarkushSiteError(MBForgeError):
    """Raised for validation / state-machine violations in site ops."""

    status_code = 422
    error_code = "validation_error"


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


__all__ = ["MarkushSiteError"]

"""SQLite data access for Markush enumeration.

Owns the ``markush_generation_runs`` / ``markush_generated_candidates`` write
path, the human decision promotion, and the server-side authorization read that
resolves a requested selection against confirmed database state. Functions take
a caller-owned ``sqlite3.Connection``; the deterministic cross-product and
substitution algorithm stay in :mod:`mbforge.domain.enumeration`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from mbforge.domain.enumeration import (
    MarkushEnumerationError,
    ResolvedFragment,
    ResolvedSiteSelection,
    SiteSelection,
)
from mbforge.foundation.ids import short_id


def _one(conn: sqlite3.Connection, sql: str, params: Any) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Selection authorization (read-only)
# ---------------------------------------------------------------------------


def resolve_authorized_selection(
    conn: sqlite3.Connection,
    *,
    scaffold_id: str,
    selection: list[SiteSelection],
) -> tuple[str, list[ResolvedSiteSelection]]:
    """Validate every selection identifier against confirmed DB state.

    Returns ``(scaffold_smiles, resolved)`` where ``resolved`` carries
    server-side fragment IDs and SMILES. Raises
    :class:`MarkushEnumerationError` before any run is created when the
    scaffold, site, fragment, or relation is missing or not confirmed.
    """
    scaffold = conn.execute(
        "SELECT smiles, status FROM markush_scaffolds WHERE scaffold_id = ?",
        (scaffold_id,),
    ).fetchone()
    if scaffold is None:
        raise MarkushEnumerationError(f"scaffold not found: {scaffold_id}")
    if scaffold["status"] != "confirmed":
        raise MarkushEnumerationError(f"scaffold is not confirmed: {scaffold_id}")

    resolved: list[ResolvedSiteSelection] = []
    for site in selection:
        site_row = conn.execute(
            """
            SELECT site_id, site_label, atom_map_num, status
            FROM markush_sites
            WHERE scaffold_id = ? AND site_label = ? AND atom_map_num = ?
            """,
            (scaffold_id, site.site_label, site.atom_map_num),
        ).fetchone()
        if site_row is None:
            raise MarkushEnumerationError(
                f"site {site.site_label}[*:{site.atom_map_num}] "
                f"not found on scaffold {scaffold_id}"
            )
        if site_row["status"] != "confirmed":
            raise MarkushEnumerationError(f"site {site.site_label} is not confirmed")

        fragments: list[ResolvedFragment] = []
        for fragment_id in site.fragments:
            fragment = conn.execute(
                "SELECT fragment_id, smiles, status FROM markush_fragments WHERE fragment_id = ?",
                (fragment_id,),
            ).fetchone()
            if fragment is None:
                raise MarkushEnumerationError(f"fragment not found: {fragment_id}")
            if fragment["status"] != "confirmed":
                raise MarkushEnumerationError(
                    f"fragment is not confirmed: {fragment_id}"
                )
            relation = conn.execute(
                """
                SELECT 1
                FROM markush_sites AS s
                LEFT JOIN markush_options AS o
                  ON o.site_id = s.site_id
                 AND o.fragment_id = ?
                 AND o.status = 'confirmed'
                LEFT JOIN markush_mounts AS m
                  ON m.site_id = s.site_id
                 AND m.fragment_id = ?
                 AND m.status = 'confirmed'
                WHERE s.site_id = ?
                  AND (o.option_id IS NOT NULL OR m.mount_id IS NOT NULL)
                """,
                (fragment_id, fragment_id, site_row["site_id"]),
            ).fetchone()
            if relation is None:
                raise MarkushEnumerationError(
                    f"fragment {fragment_id} has no confirmed relation "
                    f"to site {site.site_label}"
                )
            fragments.append(
                ResolvedFragment(
                    fragment_id=fragment_id,
                    smiles=fragment["smiles"] or "",
                )
            )
        resolved.append(
            ResolvedSiteSelection(
                site_label=site.site_label,
                atom_map_num=site.atom_map_num,
                fragments=fragments,
            )
        )
    return scaffold["smiles"] or "", resolved


# ---------------------------------------------------------------------------
# Enumeration runs
# ---------------------------------------------------------------------------


def insert_generation_run_terminal(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    scaffold_id: str,
    selection_json: str,
    theoretical_count: int,
    requested_limit: int,
    status: str,
    error: str,
) -> None:
    """Insert a finished ``rejected`` / ``empty`` run row."""
    conn.execute(
        """
        INSERT INTO markush_generation_runs
            (run_id, scaffold_id, selection, theoretical_count,
             requested_limit, status, error, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            run_id,
            scaffold_id,
            selection_json,
            theoretical_count,
            requested_limit,
            status,
            error,
        ),
    )


def record_enumeration_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    scaffold_id: str,
    selection_json: str,
    theoretical_count: int,
    requested_limit: int,
    candidates: list[dict[str, Any]],
) -> int:
    """Insert a running run row, every candidate, and the final status in one go.

    Returns the number of candidates actually written. A duplicate
    ``(run_id, combination_key)`` is skipped silently.
    """
    conn.execute(
        """
        INSERT INTO markush_generation_runs
            (run_id, scaffold_id, selection, theoretical_count,
             requested_limit, status)
        VALUES (?, ?, ?, ?, ?, 'running')
        """,
        (
            run_id,
            scaffold_id,
            selection_json,
            theoretical_count,
            requested_limit,
        ),
    )

    written = 0
    for candidate in candidates:
        try:
            conn.execute(
                """
                INSERT INTO markush_generated_candidates
                    (generated_id, run_id, scaffold_id, combination_key,
                     smiles, canonical_smiles, assignments,
                     validation_status, review_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    candidate["generated_id"],
                    run_id,
                    scaffold_id,
                    candidate["combination_key"],
                    candidate["smiles"],
                    candidate["canonical_smiles"],
                    candidate["assignments"],
                    "valid",
                ),
            )
            written += 1
        except sqlite3.IntegrityError:
            # Duplicate (run_id, combination_key) — already written by
            # an earlier loop iteration, skip silently.
            continue

    conn.execute(
        """
        UPDATE markush_generation_runs
        SET status = ?, completed_at = datetime('now')
        WHERE run_id = ?
        """,
        ("completed" if written > 0 else "empty", run_id),
    )
    return written


# ---------------------------------------------------------------------------
# Generated-candidate decisions
# ---------------------------------------------------------------------------


def get_generated_candidate(
    conn: sqlite3.Connection, generated_id: str
) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT generated_id, run_id, scaffold_id, combination_key,
               smiles, canonical_smiles, assignments, properties, review_status
        FROM markush_generated_candidates
        WHERE generated_id = ?
        """,
        (generated_id,),
    )


def confirm_generated_candidate(
    conn: sqlite3.Connection,
    *,
    generated_id: str,
    smiles: str,
    canonical_smiles: str,
    provenance_json: str,
    reason: str,
) -> None:
    """Promote a generated candidate into ``molecules`` and audit the decision."""
    conn.execute(
        """
        INSERT INTO molecules
            (mol_id, smiles, canonical_smiles, source_doc,
             source_type, status, properties, review_status)
        VALUES (?, ?, ?, 'markush_generation', 'generated',
                'active', ?, 'confirmed')
        """,
        (generated_id, smiles, canonical_smiles, provenance_json),
    )
    conn.execute(
        """
        UPDATE markush_generated_candidates
        SET review_status = 'confirmed'
        WHERE generated_id = ?
        """,
        (generated_id,),
    )
    conn.execute(
        """
        INSERT INTO markush_decisions
            (decision_id, entity_type, entity_id, action,
             previous_state, new_state, reason)
        VALUES (?, 'generated_candidate', ?, ?, ?, ?, ?)
        """,
        (
            short_id(),
            generated_id,
            "generated_confirm",
            "pending",
            "confirmed",
            reason,
        ),
    )


def reject_generated_candidate(
    conn: sqlite3.Connection, *, generated_id: str, reason: str
) -> None:
    """Reject a generated candidate without writing to ``molecules``."""
    conn.execute(
        """
        UPDATE markush_generated_candidates
        SET review_status = 'rejected'
        WHERE generated_id = ?
        """,
        (generated_id,),
    )
    conn.execute(
        """
        INSERT INTO markush_decisions
            (decision_id, entity_type, entity_id, action,
             previous_state, new_state, reason)
        VALUES (?, 'generated_candidate', ?, ?, ?, ?, ?)
        """,
        (
            short_id(),
            generated_id,
            "generated_reject",
            "pending",
            "rejected",
            reason,
        ),
    )


def list_run_results(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    """Return every generated candidate row for a given run."""
    rows = conn.execute(
        """
        SELECT generated_id, smiles, canonical_smiles, combination_key,
               assignments, validation_status, review_status
        FROM markush_generated_candidates
        WHERE run_id = ?
        ORDER BY canonical_smiles
        """,
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


__all__ = [
    "confirm_generated_candidate",
    "get_generated_candidate",
    "insert_generation_run_terminal",
    "list_run_results",
    "record_enumeration_run",
    "reject_generated_candidate",
    "resolve_authorized_selection",
]

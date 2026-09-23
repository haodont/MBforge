"""Persistence half of Markush enumeration.

Owns the ``markush_generation_runs`` / ``markush_generated_candidates``
write path and the human decision promotion. The deterministic
cross-product algorithm and authorization rules live in
:mod:`mbforge.domain.enumeration`.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from mbforge.domain.enumeration import (
    GenerationResult,
    MarkushEnumerationError,
    SiteSelection,
    _canonical_smiles,
    _sorted_combinations,
    _substitute,
    resolve_authorized_selection,
    theoretical_count,
)
from mbforge.foundation.errors import NotFoundError
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.use_cases.markush.enumeration")


def run_enumeration(
    conn: sqlite3.Connection,
    *,
    scaffold_id: str,
    selection: list[SiteSelection],
    requested_limit: int,
) -> GenerationResult:
    """Persist an enumeration run and write every valid candidate.

    The selection is first resolved and authorized against the database:
    every scaffold, site, and fragment must exist and be ``confirmed``,
    and every fragment must be linked through a confirmed option or
    mount. Invalid selections raise :class:`MarkushEnumerationError`
    without creating a run.

    ``requested_limit`` is hard-enforced: if the theoretical cross-product
    exceeds it, no rows are written and the run row carries
    ``status='rejected'``. Otherwise the surviving combinations are
    materialised, canonicalised, and deduplicated before insertion.
    """
    scaffold_smiles, resolved = resolve_authorized_selection(
        conn,
        scaffold_id=scaffold_id,
        selection=selection,
    )
    total = theoretical_count(selection)
    if total > requested_limit:
        run_id = short_id()
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
                json.dumps(
                    [{"label": s.site_label, "n": len(s.fragments)} for s in selection]
                ),
                total,
                requested_limit,
                "rejected",
                f"theoretical_count {total} > requested_limit {requested_limit}",
            ),
        )
        return GenerationResult(
            run_id=run_id,
            theoretical_count=total,
            written_count=0,
            truncated=True,
            status="rejected",
            error="theoretical_count exceeds requested_limit",
        )
    if total == 0:
        run_id = short_id()
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
                json.dumps([{"label": s.site_label, "n": 0} for s in selection]),
                0,
                requested_limit,
                "empty",
                "no fragments in any site",
            ),
        )
        return GenerationResult(
            run_id=run_id,
            theoretical_count=0,
            written_count=0,
            truncated=False,
            status="empty",
        )

    run_id = short_id()
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
            json.dumps(
                [{"label": s.site_label, "n": len(s.fragments)} for s in resolved]
            ),
            total,
            requested_limit,
        ),
    )

    written = 0
    seen_canonicals: set[str] = set()
    for combination in _sorted_combinations(resolved):
        if written >= requested_limit:
            break
        smi = _substitute(scaffold_smiles, resolved, combination)
        if smi is None:
            continue
        canonical = _canonical_smiles(smi)
        if canonical is None:
            continue
        if canonical in seen_canonicals:
            continue
        seen_canonicals.add(canonical)
        combination_key = "|".join(f.fragment_id for f in combination)
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
                    short_id(),
                    run_id,
                    scaffold_id,
                    combination_key,
                    smi,
                    canonical,
                    json.dumps(
                        [
                            {
                                "site_label": s.site_label,
                                "atom_map_num": s.atom_map_num,
                                "fragment_id": frag.fragment_id,
                                "fragment_smiles": frag.smiles,
                            }
                            for s, frag in zip(resolved, combination, strict=True)
                        ]
                    ),
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
    return GenerationResult(
        run_id=run_id,
        theoretical_count=total,
        written_count=written,
        truncated=written < total,
        status="completed" if written > 0 else "empty",
    )


def apply_generated_decision(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    action: str,
    reason: str,
) -> dict[str, str]:
    """Confirm or reject a generated enumeration candidate.

    ``confirm`` promotes the candidate into the ``molecules`` table and
    flips ``review_status='confirmed'``; ``reject`` flips it to
    ``rejected`` without writing to ``molecules``. An audit row is
    always recorded in ``markush_decisions``.
    """
    row = conn.execute(
        """
        SELECT generated_id, run_id, scaffold_id, combination_key,
               smiles, canonical_smiles, assignments, properties, review_status
        FROM markush_generated_candidates
        WHERE generated_id = ?
        """,
        (entity_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"generated candidate not found: {entity_id}")
    if row["review_status"] != "pending":
        raise MarkushEnumerationError(
            f"generated candidate is already {row['review_status']}"
        )
    if action not in {"confirm", "reject"}:
        raise MarkushEnumerationError(f"unsupported action: {action}")

    if action == "confirm":
        assignments = json.loads(row["assignments"]) if row["assignments"] else []
        provenance = {
            "markush_generation": {
                "generated_id": row["generated_id"],
                "run_id": row["run_id"],
                "scaffold_id": row["scaffold_id"],
                "combination_key": row["combination_key"],
                "assignments": assignments,
            }
        }
        conn.execute(
            """
            INSERT INTO molecules
                (mol_id, smiles, canonical_smiles, source_doc,
                 source_type, status, properties, review_status)
            VALUES (?, ?, ?, 'markush_generation', 'generated',
                    'active', ?, 'confirmed')
            """,
            (
                entity_id,
                row["smiles"],
                row["canonical_smiles"],
                json.dumps(provenance, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            UPDATE markush_generated_candidates
            SET review_status = 'confirmed'
            WHERE generated_id = ?
            """,
            (entity_id,),
        )
        new_state = "confirmed"
    else:
        conn.execute(
            """
            UPDATE markush_generated_candidates
            SET review_status = 'rejected'
            WHERE generated_id = ?
            """,
            (entity_id,),
        )
        new_state = "rejected"

    conn.execute(
        """
        INSERT INTO markush_decisions
            (decision_id, entity_type, entity_id, action,
             previous_state, new_state, reason)
        VALUES (?, 'generated_candidate', ?, ?, ?, ?, ?)
        """,
        (
            short_id(),
            entity_id,
            f"generated_{action}",
            "pending",
            new_state,
            reason,
        ),
    )
    result: dict[str, str] = {
        "generated_id": entity_id,
        "review_status": new_state,
    }
    if action == "confirm":
        result["mol_id"] = entity_id
    return result


def list_run_results(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    """Return every generated candidate for a given run."""
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
    return [
        {
            "generated_id": row["generated_id"],
            "smiles": row["smiles"],
            "canonical_smiles": row["canonical_smiles"],
            "combination_key": row["combination_key"],
            "assignments": json.loads(row["assignments"]),
            "validation_status": row["validation_status"],
            "review_status": row["review_status"],
        }
        for row in rows
    ]


__all__ = [
    "apply_generated_decision",
    "list_run_results",
    "run_enumeration",
]

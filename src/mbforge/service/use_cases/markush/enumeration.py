"""Persistence-orchestration half of Markush enumeration.

Owns the ``markush_generation_runs`` / ``markush_generated_candidates``
write path and the human decision promotion. The raw SQL lives behind
:class:`~mbforge.ports.repositories.MarkushRepository`; the deterministic
cross-product algorithm and authorization rules live in
:mod:`mbforge.domain.enumeration`.
"""

from __future__ import annotations

import json
from typing import Any

from mbforge.domain.enumeration import (
    GenerationResult,
    MarkushEnumerationError,
    SiteSelection,
    _canonical_smiles,
    _sorted_combinations,
    _substitute,
    theoretical_count,
)
from mbforge.foundation.errors import NotFoundError
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger
from mbforge.ports.repositories import MarkushRepository

logger = get_logger("mbforge.service.use_cases.markush.enumeration")


def resolve_authorized_selection(
    repository: MarkushRepository,
    *,
    scaffold_id: str,
    selection: list[SiteSelection],
) -> tuple[str, list[Any]]:
    """Resolve and authorize a selection against confirmed database state."""
    return repository.resolve_authorized_selection(
        scaffold_id=scaffold_id, selection=selection
    )


def run_enumeration(
    repository: MarkushRepository,
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
    scaffold_smiles, resolved = repository.resolve_authorized_selection(
        scaffold_id=scaffold_id,
        selection=selection,
    )
    total = theoretical_count(selection)
    if total > requested_limit:
        run_id = short_id()
        repository.insert_generation_run_terminal(
            run_id=run_id,
            scaffold_id=scaffold_id,
            selection_json=json.dumps(
                [{"label": s.site_label, "n": len(s.fragments)} for s in selection]
            ),
            theoretical_count=total,
            requested_limit=requested_limit,
            status="rejected",
            error=f"theoretical_count {total} > requested_limit {requested_limit}",
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
        repository.insert_generation_run_terminal(
            run_id=run_id,
            scaffold_id=scaffold_id,
            selection_json=json.dumps(
                [{"label": s.site_label, "n": 0} for s in selection]
            ),
            theoretical_count=0,
            requested_limit=requested_limit,
            status="empty",
            error="no fragments in any site",
        )
        return GenerationResult(
            run_id=run_id,
            theoretical_count=0,
            written_count=0,
            truncated=False,
            status="empty",
        )

    run_id = short_id()
    candidates: list[dict[str, Any]] = []
    seen_canonicals: set[str] = set()
    for combination in _sorted_combinations(resolved):
        if len(candidates) >= requested_limit:
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
        candidates.append(
            {
                "generated_id": short_id(),
                "combination_key": combination_key,
                "smiles": smi,
                "canonical_smiles": canonical,
                "assignments": json.dumps(
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
            }
        )

    written = repository.record_enumeration_run(
        run_id=run_id,
        scaffold_id=scaffold_id,
        selection_json=json.dumps(
            [{"label": s.site_label, "n": len(s.fragments)} for s in resolved]
        ),
        theoretical_count=total,
        requested_limit=requested_limit,
        candidates=candidates,
    )
    return GenerationResult(
        run_id=run_id,
        theoretical_count=total,
        written_count=written,
        truncated=written < total,
        status="completed" if written > 0 else "empty",
    )


def apply_generated_decision(
    repository: MarkushRepository,
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
    row = repository.get_generated_candidate(entity_id)
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
        repository.confirm_generated_candidate(
            generated_id=entity_id,
            smiles=row["smiles"],
            canonical_smiles=row["canonical_smiles"],
            provenance_json=json.dumps(provenance, ensure_ascii=False),
            reason=reason,
        )
        new_state = "confirmed"
    else:
        repository.reject_generated_candidate(
            generated_id=entity_id,
            reason=reason,
        )
        new_state = "rejected"

    result: dict[str, str] = {
        "generated_id": entity_id,
        "review_status": new_state,
    }
    if action == "confirm":
        result["mol_id"] = entity_id
    return result


def list_run_results(
    repository: MarkushRepository, run_id: str
) -> list[dict[str, Any]]:
    """Return every generated candidate for a given run."""
    rows = repository.list_run_results(run_id)
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
    "resolve_authorized_selection",
    "run_enumeration",
]

"""Promote one recognized drawing to a concrete structure a link can reference.

The Markush role gate is deliberately conservative: a closed SMILES whose
surrounding prose mentions R-groups, generic formulae or a mixture is withheld
from the concrete library instead of being silently imported. That refusal is
right, but it has no other half — a final compound printed under an example
heading whose section also prints R-group definitions is withheld too, so no
``molecules`` row exists and no reading can ever be linked to it.

This use case is that other half. It promotes exactly one drawing a caller has
identified (by its structure evidence or its canonical SMILES), records who
decided and why, and leaves every other withheld drawing alone. It never
invents a structure: the candidate must already exist in the document's
molecule evidence, must be a closed structure (no dummy atom, not a Markush
scaffold) and must not have been rejected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.foundation.errors import ConflictError, NotFoundError, ValidationError


def promote_structure(
    library_root: str | Path,
    doc_id: str,
    *,
    smiles: str = "",
    evidence_id: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Persist one recognized concrete drawing as a stored molecule.

    Args:
        library_root: active library root.
        doc_id: the document whose evidence holds the drawing.
        smiles: canonical SMILES of the drawing to promote.
        evidence_id: the molecule evidence row of that drawing (alternative to
            ``smiles``; the two may be given together, which pins the exact
            printing).
        reason: why the promotion is evidence-backed; stored on the molecule so
            a later reader can see it was a decision, not a rule.

    Returns:
        ``{mol_id, name, page, promoted}``; ``promoted`` is false when the
        molecule was already stored (an idempotent repeat).
    """
    from mbforge.service.pipeline.artifacts.hydration import load_detections
    from mbforge.service.pipeline.persist.molecules import (
        persist_molecule_candidates,
    )
    from mbforge.service.ports import get_repositories

    if not smiles.strip() and not evidence_id.strip():
        raise ValidationError(
            "promote_structure needs a smiles or a structure evidence id"
        )

    loaded = load_detections(str(library_root), doc_id)
    if loaded is None:
        raise NotFoundError("no molecule evidence for this document", detail=doc_id)
    candidates, _summary = loaded

    target = None
    for candidate in candidates:
        if evidence_id and any(
            getattr(detection, "evidence_id", None) == evidence_id
            for detection in candidate.detections
        ):
            target = candidate
            break
        if smiles and candidate.canonical_smiles == smiles.strip():
            target = candidate
            break
    if target is None:
        raise NotFoundError(
            "structure not recognized in this document",
            detail=evidence_id or smiles,
        )

    canonical = (target.canonical_smiles or "").strip()
    if not canonical:
        raise ValidationError("the drawing has no canonical structure")
    if "*" in canonical or target.properties.get("markush") is True:
        raise ConflictError(
            "a Markush scaffold or fragment cannot be promoted to a concrete structure",
            detail=evidence_id or canonical,
        )
    if target.status == "rejected":
        raise ConflictError(
            "a rejected structure cannot be promoted", detail=evidence_id or canonical
        )

    repositories = get_repositories(str(library_root))
    existing = repositories.molecules.identity_fields([canonical])
    if canonical in existing:
        row = existing[canonical]
        return {
            "mol_id": canonical,
            "name": row.get("name", ""),
            "page": None,
            "promoted": False,
        }

    target.properties["structure_role"] = "complete"
    target.properties["structure_role_reasons"] = ["promoted_by_agent"]
    target.properties["promotion"] = {
        "reason": reason,
        "evidence_id": evidence_id,
    }
    persist_molecule_candidates(str(library_root), doc_id, [target])

    page = None
    if target.detections:
        raw_page = target.detections[0].page
        page = raw_page + 1 if isinstance(raw_page, int) else None
    return {
        "mol_id": canonical,
        "name": target.name,
        "page": page,
        "promoted": True,
    }


__all__ = ["promote_structure"]

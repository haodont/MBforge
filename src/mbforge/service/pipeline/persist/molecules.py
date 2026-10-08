"""Persist canonical molecule candidates to the database.

The persistence layer owns the SQL; this module keeps the candidate skip rules
and delegates the write to the ``MoleculeRepository`` port.

For each candidate (a single canonical SMILES, possibly with multiple
detections) the repository upserts a `molecules` row keyed by
`canonical_smiles` and inserts one `molecule_detections` row per primary
detection, carrying its `evidence_id` link to the canonical `source_evidence`
row. The retired `evidence` table no longer exists.

Page semantics: `molecule_detections.page` stays a 0-based `PageIndex`; the
molecule-evidence projection exposes the 1-based `PageNumber` (`page + 1`).
"""

from __future__ import annotations

from mbforge.domain.molecule import Molecule
from mbforge.foundation.logger import get_logger
from mbforge.service.ports import get_repositories

logger = get_logger(__name__)


def persist_molecule_candidates(
    library_root: str,
    doc_id: str,
    candidates: list[Molecule],
) -> None:
    """Upsert canonical molecule rows + insert detection rows.

    Candidates are filtered to the persistable subset first; the write itself
    is delegated to the molecule repository.
    """
    persistable = filter_persistable_candidates(doc_id, candidates)
    if not persistable:
        return
    get_repositories(library_root).molecules.persist_candidates(doc_id, persistable)


def filter_persistable_candidates(
    doc_id: str,
    candidates: list[Molecule],
    *,
    warn: bool = True,
) -> list[Molecule]:
    """Apply the persist loop's skip rules, preserving candidate order.

    Filtering before matching keeps the shared activity matcher from
    consuming rows on behalf of candidates that can never be persisted:
    rejected, non-``complete`` structure role, no detections, no detection
    page, or no canonical SMILES.

    Also used by read paths (by-location overlay queries) to reproduce the
    persisted subset from the normalized molecule results; pass ``warn=False``
    there — skipped candidates are the normal case for a read, not a
    persistence anomaly worth logging.
    """
    persistable: list[Molecule] = []
    for c in candidates:
        if c.status == "rejected":
            continue
        properties = getattr(c, "properties", {})
        role = (
            properties.get("structure_role") if isinstance(properties, dict) else None
        )
        if role is None:
            # This function is also used directly by a few integrations;
            # do not let an unclassified candidate bypass the Markush
            # boundary merely because the persist step was skipped.
            from mbforge.service.pipeline.detection.structure_role import (
                classify_structure_role,
            )

            role = classify_structure_role(c)
        if role != "complete":
            continue
        if not c.detections:
            if warn:
                logger.warning(
                    "Skipping candidate with no detections for %s (%s)",
                    doc_id,
                    c.esmiles,
                )
            continue
        if c.detections[0].page is None:
            # ``molecule_detections.page`` is NOT NULL and a detection
            # without a page must never be defaulted to the first page,
            # so skip the candidate instead of aborting the whole
            # document persist with an IntegrityError.
            if warn:
                logger.warning(
                    "Skipping candidate with no detection page for %s (%s)",
                    doc_id,
                    c.esmiles,
                )
            continue
        if not c.canonical_smiles:
            if warn:
                logger.warning(
                    "Skipping candidate with no canonical_smiles for %s",
                    doc_id,
                )
            continue
        persistable.append(c)
    return persistable

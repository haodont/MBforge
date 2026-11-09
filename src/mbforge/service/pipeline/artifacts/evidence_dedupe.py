"""Same-location arbitration for the canonical source evidence.

``evidence_id`` is the location ``(doc_id, page, bbox)`` and is the table's
primary key, so two claims on the same box must collapse to one row before the
insert. This module owns that arbitration plus the molecule-over-figure rule for
overlapping boxes; it is pure (no SQL, no producer handles) so :func:`mint_evidence`
can stay the single place that turns page claims into rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import (
    IMAGE,
    MOLECULE,
    category_of,
    kind_rank,
)


def join_evidence_dedupe(items: Sequence[SourceEvidence]) -> list[SourceEvidence]:
    """Arbitrate evidence so one location yields one row.

    Two rules:

    1. **One row per location** ``(doc_id, page, bbox)``. ``evidence_id`` is the
       location, and it is the table's PRIMARY KEY, so two claims on the same box
       must collapse to a single row before the insert. The surviving row keeps
       the winner's ``kind``.
    2. **Molecule over figure** for overlapping (but not identical) boxes. Text is
       never discarded here — its raw text is an independent fact used by
       OCR/layout readers.

    A claim that carries content is never displaced by one that does not:
    ``raw_text`` outranks box geometry, so a layout region re-typed to a molecule
    (R3) — which claims the molecule with MolDet's own geometry but no payload —
    leaves the molecule pass' row, and its SMILES, in place.

    Comparison is by **category**, not by raw label: producers name their regions
    freely (``chem`` / ``figcx`` / …), so two figure regions from one model can
    carry different labels while playing the same role.
    """
    from mbforge.service.pipeline.detection.bbox_filter import bbox_area, bbox_iou

    def sort_key(item: SourceEvidence) -> tuple[object, ...]:
        # Molecule first, then content, then larger box, then the higher-ranked
        # category.  Content before size: the two sides of an overlap are usually
        # one molecule seen by two detectors, and only the molecule pass' row
        # holds the recognition payload.  The size and rank keys only ever decide
        # between equally content-bearing boxes, so the winner stays deterministic.
        return (
            item.page,
            0 if category_of(item.kind) == MOLECULE else 1,
            0 if item.raw_text else 1,
            -bbox_area(item.bbox),
            -kind_rank(item.kind),
            item.evidence_id,
        )

    geometric = {MOLECULE, IMAGE}
    kept: list[SourceEvidence] = []
    seen_locations: set[tuple[str, int, tuple[float, float, float, float]]] = set()
    for item in sorted(items, key=sort_key):
        location = (item.doc_id, item.page, item.bbox)
        if location in seen_locations:
            continue
        discard = False
        item_category = category_of(item.kind)
        for existing in kept:
            if existing.page != item.page:
                continue
            existing_category = category_of(existing.kind)
            if existing_category not in geometric or item_category not in geometric:
                continue
            iou = bbox_iou(existing.bbox, item.bbox)
            same_region_kind = existing_category == item_category
            if same_region_kind and iou <= 0.5:
                continue
            if not same_region_kind and iou <= 0.0:
                continue
            if existing_category == MOLECULE and item_category == IMAGE:
                discard = True
                break
            if existing_category == item_category == MOLECULE:
                # Molecule boxes are sorted content-then-size-first, so the
                # first box wins and lower-value duplicate detections drop out.
                discard = True
                break
            if existing_category == item_category == IMAGE:
                discard = True
                break
        if not discard:
            kept.append(item)
            seen_locations.add(location)
    return kept


__all__ = ["join_evidence_dedupe"]

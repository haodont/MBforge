"""Persist extracted activity records to the ``activities`` table.

This is the structured companion of ``persist_molecule_candidates``. The
existing ``evidence`` table records *where* an activity came from (page /
table_idx / row_idx) but does not store target / assay / value in queryable
columns. SAR queries (rank by target, find best activity, group by assay)
need those fields in a column, so this stage writes a parallel
``activities`` row per matched record.

Idempotency:
    A re-ingest of the same document deletes its ``evidence`` rows
    (see ``PersistStage._compensate_molecule_persistence`` and
    ``delete_document_molecule_data``). Once records are matched, this
    function also deletes the document's prior ``activities`` rows so the
    table stays consistent with the evidence chain (early exits with no
    records or no candidates leave prior rows untouched).

Output:
    ``activity_id`` is a deterministic UUID5 derived from the canonical
    activity tuple (mol_id, doc_id, activity_type, target, assay_description,
    value_original, page_num, table_idx, row_idx, col_idx, row_label,
    reference_key, qualitative_raw). This
    keeps the same activity stable across re-ingests without an explicit
    UNIQUE constraint, and lets callers reference specific records.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from mbforge.application.pipeline.activity.matching import match_activities
from mbforge.application.pipeline.activity.normalization import (
    canonical_value_for_legacy,
)
from mbforge.foundation.ids import deterministic_id
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

# Stable namespace for activity UUID5 (any fixed UUID works; keep constant).
_ACTIVITY_NS = "5b3c0f2a-7e2d-4d36-8d6e-1c5b8a0d4f6e"


def _activity_id(
    mol_id: str,
    doc_id: str,
    rec: Any,
) -> str:
    """Return a deterministic UUID5 for an activity record."""
    payload = "|".join(
        [
            mol_id,
            doc_id,
            str(getattr(rec, "activity_type", "") or ""),
            str(getattr(rec, "target", "") or ""),
            str(
                getattr(rec, "assay_description", "")
                or getattr(rec, "assay_type", "")
                or ""
            ),
            f"{float(getattr(rec, 'value_original', 0) or 0):.6f}",
            str(getattr(rec, "page_num", "") or ""),
            str(getattr(rec, "table_idx", "") or ""),
            str(getattr(rec, "row_idx", "") or ""),
            str(getattr(rec, "col_idx", "") or ""),
            str(getattr(rec, "row_label", "") or ""),
            str(getattr(rec, "reference_key", "") or ""),
            str(getattr(rec, "qualitative_raw", "") or ""),
        ]
    )
    return deterministic_id(_ACTIVITY_NS, payload)


def _build_mol_id_map(
    candidates: list[Any],
    activity_records: list[Any],
    activity_guard: Any | None = None,
) -> dict[int, str]:
    """Map activity record index → mol_id using the shared matcher.

    PIPE-08: matching is delegated to
    :func:`mbforge.application.pipeline.activity.matching.match_activities`, the single
    owner of the row-alignment rules and ``used_rows`` tracking, so the
    ``activities`` rows join the same canonical molecule the evidence rows
    already point at. Only row-level matches (``kind == "table_row"``)
    produce ``activities`` rows; the low-confidence same-page fallback
    stays evidence-only. Records that fail to match a candidate are absent
    from the map — the pipeline routes those records to the human review
    queue instead of inserting orphan activity rows.
    """
    return {
        match.record_key: match.candidate_key
        for match in match_activities(
            candidates, activity_records, candidate_guard=activity_guard
        )
        if match.kind == "table_row"
    }


def delete_activities_for_doc(conn: sqlite3.Connection, doc_id: str) -> int:
    """Remove all activity rows for a document. Returns deleted count."""
    cur = conn.execute("DELETE FROM activities WHERE doc_id = ?", (doc_id,))
    return cur.rowcount


def delete_activity_review_items_for_doc(conn: sqlite3.Connection, doc_id: str) -> int:
    """Remove pending ``activity_match`` review items for a document.

    Re-ingest refreshes the orphan set from the current match results, so
    stale pending items — e.g. an early run that matched nothing — must not
    survive alongside the new ones. Resolved items keep their status and
    audit history (``markush_decisions``) and are left untouched.
    """
    cur = conn.execute(
        "DELETE FROM review_items WHERE doc_id = ? AND kind = 'activity_match' "
        "AND status = 'pending'",
        (doc_id,),
    )
    return cur.rowcount


def persist_activities(
    library_root: str,
    doc_id: str,
    activity_records: list[Any],
    candidates: list[Any] | None = None,
    conn: sqlite3.Connection | None = None,
    activity_guard: Any | None = None,
) -> int:
    """Write activity records to a JSON file (temporarily).

    Args:
        library_root: Project root directory.
        doc_id: Source document ID.
        activity_records: ActivityRecord list from the activity stage.
        candidates: Optional list of Molecule. When provided, the
            function resolves each activity to a ``mol_id`` using the same
            row-alignment rules as ``persist_molecule_candidates``. When
            ``None``, every record is skipped (orphan activities are not
            useful for SAR queries).
        conn: Unused (kept for API compatibility).
        activity_guard: Optional per-candidate veto callable forwarded to
            :func:`match_activities` (see ``candidate_guard`` there). Vetoed
            candidates produce no ``mol_id``, so their records land in the
            review queue as ``orphan_activity``.

    Returns:
        Number of activities written.
    """
    if not activity_records:
        return 0
    if candidates is None:
        logger.debug(
            "persist_activities: candidates omitted for %s; preserving no-op contract",
            doc_id,
        )
        return 0
    if not candidates:
        logger.debug(
            "persist_activities: no candidates provided for %s; queueing %d records for review",
            doc_id,
            len(activity_records),
        )

    mol_id_map = _build_mol_id_map(candidates, activity_records, activity_guard)

    # Build activity records as dicts for JSON serialization
    activities_list = []

    for index, rec in enumerate(activity_records):
        mol_id = mol_id_map.get(index)
        confidence = float(getattr(rec, "confidence", 0) or 0)

        if not mol_id or confidence < 0.5:
            # Skip low-confidence or orphan activities for now
            continue

        activity_dict = {
            "activity_id": _activity_id(mol_id, doc_id, rec),
            "mol_id": mol_id,
            "doc_id": doc_id,
            "activity_type": getattr(rec, "activity_type", "IC50"),
            "value": canonical_value_for_legacy(rec),
            "value_original": getattr(rec, "value_original", None),
            "unit_original": getattr(rec, "unit", None),
            "operator": getattr(rec, "operator", "="),
            "measurement_kind": getattr(rec, "measurement_kind", "quantitative"),
            "metric": getattr(rec, "metric", None)
            or getattr(rec, "activity_type", None),
            "value_canonical": getattr(rec, "value_canonical", None),
            "unit_canonical": getattr(rec, "unit_canonical", None),
            "operator_original": getattr(rec, "operator_original", None),
            "scale": getattr(rec, "scale", "linear"),
            "value_text": getattr(rec, "value_text", None),
            "qualitative_raw": getattr(rec, "qualitative_raw", None),
            "qualitative_rank": getattr(rec, "qualitative_rank", None),
            "qualitative_scheme": getattr(rec, "qualitative_scheme", None),
            "qualitative_label": getattr(rec, "qualitative_label", None),
            "reference_raw": getattr(rec, "reference_raw", None),
            "reference_key": getattr(rec, "reference_key", None),
            "reference_type": getattr(rec, "reference_type", None),
            "target": getattr(rec, "target", None),
            "assay_type": getattr(rec, "assay_type", None),
            "assay_description": getattr(rec, "assay_type", None),
            "confidence": confidence,
            "page_num": getattr(rec, "page_num", None),
            "table_idx": getattr(rec, "table_idx", None),
            "row_idx": getattr(rec, "row_idx", None),
            "col_idx": getattr(rec, "col_idx", None),
            "row_label": getattr(rec, "row_label", None),
            "row_smiles": getattr(rec, "row_smiles", None),
            "raw_text": (getattr(rec, "raw_text", "") or "")[:500],
        }
        activities_list.append(activity_dict)

    # Write to JSON file in the document's storage directory
    layout = LibraryLayout(library_root)
    doc_storage_dir = Path(layout.storage_dir(doc_id))
    doc_storage_dir.mkdir(parents=True, exist_ok=True)

    activities_file = doc_storage_dir / "activities.json"
    activities_file.write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "count": len(activities_list),
                "activities": activities_list,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    written = len(activities_list)
    logger.info(
        "Wrote %d/%d activity records to %s for %s",
        written,
        len(activity_records),
        activities_file,
        doc_id,
    )
    return written

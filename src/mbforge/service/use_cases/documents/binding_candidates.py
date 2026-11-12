"""Candidate material for structure-activity binding decisions.

The read surface for agent-driven binding: for every designation a document
prints — in a reading, on a drawing, or in a compound entry — report the
structures that claim it and the evidence a reader needs to choose. It joins
existing read surfaces (activity records, structure verification, the Patent
snapshot, the review queue and the table evidence) and writes nothing; the
choice belongs to the agent, not to this module.

Nothing here decides or applies an attribution. The package is the material a
decision is made from, so a caller can compare what the rules resolved against
what the document actually printed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mbforge.service.use_cases.documents.activity_queries import list_activity_records
from mbforge.service.use_cases.documents.structure_verification import verify_structures

#: Readings are context, not the decision unit; cap them so one large document
#: cannot dominate the package.
_READING_LIMIT = 500
#: ``verify_structures`` returns at most 100 rows per call.
_STRUCTURE_PAGE_SIZE = 100
#: Review items are the human-decision backlog; cap them for the same reason.
_REVIEW_LIMIT = 200
#: A structure drawing left in a table cell as a placeholder token.
_TABLE_TOKEN_RE = re.compile(r"\[MOL:\d+\]")


def _candidate_structures(
    library_root: str | Path, doc_id: str
) -> list[dict[str, Any]]:
    """Every structure that carries at least one designation, with its evidence."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        report = verify_structures(
            library_root, doc_id, offset=offset, limit=_STRUCTURE_PAGE_SIZE
        )
        items = list(report.get("items") or [])
        rows.extend(item for item in items if item.get("label_keys"))
        offset += len(items)
        if not items or offset >= int(report.get("total") or 0):
            return rows


def _entries(library_root: str | Path, doc_id: str) -> list[dict[str, Any]]:
    """Compound entries from the committed Patent snapshot (none without it)."""
    from mbforge.service.use_cases.documents.patent_facts import load_patent_facts

    facts = load_patent_facts(library_root, doc_id)
    if facts is None:
        return []
    return [dict(entry) for entry in facts.entries]


def _review_items(library_root: str | Path, doc_id: str) -> list[dict[str, Any]]:
    """Pending review items for the document: the human-decision backlog.

    Reads the repository port directly, as the other document use cases do:
    ``review_queue.queue_page`` re-resolves the root against the global config,
    which a scratch library (a test or a one-off read) is not.
    """
    from mbforge.service.ports import get_repositories

    items, _total = get_repositories(str(library_root)).review.list_queue(
        kind=None,
        status="pending",
        doc_id=doc_id,
        page=1,
        page_size=_REVIEW_LIMIT,
    )
    return [dict(item) for item in items]


def _table_cells(library_root: str | Path, doc_id: str) -> list[dict[str, Any]]:
    """```[MOL:n]``` tokens printed in table cells.

    The token keeps a drawing's row/column position, but the token → molecule
    mapping lives in the layout region's ``molecule_cells`` and is not persisted
    in SQL, so the token is reported with its page and evidence row and no
    structure is claimed for it.
    """
    from mbforge.service.use_cases.documents import source_evidence

    cells: list[dict[str, Any]] = []
    for row in source_evidence.list_evidence(library_root, doc_id, kind="tab"):
        tokens = _TABLE_TOKEN_RE.findall(str(getattr(row, "raw_text", "") or ""))
        if not tokens:
            continue
        cells.append(
            {
                "page": getattr(row, "page", None),
                "evidence_id": getattr(row, "evidence_id", ""),
                "tokens": tokens,
            }
        )
    return cells


def _add_unique(values: list[Any], value: Any) -> None:
    if value is not None and value not in values:
        values.append(value)


def _designation_index(
    readings: list[dict[str, Any]],
    structures: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Every designation the document prints, with where it was seen.

    The key space is the pipeline's own (``normalize_coref_label`` for
    structures, ``reference_key`` for readings, ``label_key`` for entries), so
    the same key reaches the same slot from every surface. No global mapping is
    assumed: the index only collects what the document actually printed.
    """
    index: dict[str, dict[str, Any]] = {}

    def slot(key: str) -> dict[str, Any]:
        item = index.get(key)
        if item is None:
            item = {
                "label_key": key,
                # Filled from the first surface that printed the designation;
                # falls back to the key below when none did.
                "label_raw": "",
                "reference_types": [],
                "pages": [],
                "context_types": [],
                "reading_ids": [],
                "has_reading": False,
            }
            index[key] = item
        return item

    for reading in readings:
        key = str(reading.get("reference_key") or "").strip()
        if not key:
            continue
        item = slot(key)
        raw = reading.get("reference_raw")
        if raw and not item["label_raw"]:
            item["label_raw"] = raw
        _add_unique(item["reference_types"], reading.get("reference_type"))
        _add_unique(item["pages"], reading.get("page_num"))
        _add_unique(item["context_types"], "reading")
        _add_unique(item["reading_ids"], reading.get("activity_id"))
        item["has_reading"] = True

    for structure in structures:
        for key in structure.get("label_keys") or []:
            item = slot(str(key))
            _add_unique(item["pages"], structure.get("page"))
            _add_unique(item["context_types"], "structure_label")

    for entry in entries:
        key = str(entry.get("label_key") or "").strip()
        if not key:
            continue
        item = slot(key)
        raw = entry.get("label_raw")
        if raw and not item["label_raw"]:
            item["label_raw"] = raw
        _add_unique(item["context_types"], "entry")

    for item in index.values():
        if not item["label_raw"]:
            item["label_raw"] = item["label_key"]
    return index


def _attribution(reading: dict[str, Any]) -> dict[str, Any] | None:
    """The reading's current structure link, reduced to what decides precedence."""
    links = reading.get("attributions") or []
    if not links:
        return None
    first = links[0]
    return {
        "mol_id": str(first.get("mol_id") or ""),
        "method": str(first.get("method") or ""),
        "confidence": first.get("confidence"),
        "review_status": str(first.get("review_status") or ""),
    }


def _reading_ref(reading: dict[str, Any]) -> dict[str, Any]:
    """One reading, compact: what it printed and whether a structure owns it."""
    return {
        "measurement_id": reading.get("activity_id"),
        "label_key": reading.get("reference_key") or "",
        "label_raw": reading.get("reference_raw") or "",
        "reference_type": reading.get("reference_type") or "",
        "metric": reading.get("metric") or "",
        "value": reading.get("value"),
        "unit": reading.get("unit_original") or "",
        "operator": reading.get("operator") or "",
        "qualitative": reading.get("qualitative_label") or "",
        "page": reading.get("page_num"),
        "table_idx": reading.get("table_idx"),
        "row_idx": reading.get("row_idx"),
        "attributed": bool(reading.get("attributed")),
        "mol_ids": list(reading.get("mol_ids") or []),
        "reasons": list(reading.get("reasons") or []),
    }


def _owns(counts: dict[str, int], key: str) -> bool:
    """Whether *key* is the designation most of the structure's drawings carry.

    Same rule the association applies: a minority printing is a misreading of
    the neighbouring compound, and a tie establishes nothing.
    """
    own = counts.get(key, 0)
    if own <= 0:
        return False
    return all(own > count for other, count in counts.items() if other != key)


def _candidate_ref(row: dict[str, Any], key: str) -> dict[str, Any]:
    """One structure that claims a designation, with the evidence to check it."""
    entry = row.get("entry")
    counts = dict(row.get("designation_counts") or {})
    return {
        # A detected structure carries no molecule id of its own; the stored
        # molecule is keyed by its canonical SMILES, which is the identifier an
        # attribution must reference.
        "mol_id": str(row.get("mol_id") or row.get("canonical_smiles") or ""),
        "smiles": row.get("canonical_smiles") or row.get("smiles") or "",
        "name": row.get("name", ""),
        "labels": list(row.get("labels") or []),
        "label_keys": list(row.get("label_keys") or []),
        "label_sources": list(row.get("label_sources") or []),
        "designation_counts": counts,
        "owns": _owns(counts, key),
        "page": row.get("page"),
        "bbox": row.get("bbox"),
        "detection_score": row.get("detection_score", 0.0),
        "structure_kind": row.get("structure_kind", "concrete"),
        "formula": row.get("formula", ""),
        "exact_mass": row.get("exact_mass"),
        "mass_check": row.get("mass_check", "no_printed_mass"),
        "entry": dict(entry) if isinstance(entry, dict) else None,
    }


def binding_candidates(
    library_root: str | Path,
    doc_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """The candidate material package for one document's binding decisions.

    Reads only: readings (with their current attribution), the structures that
    carry a designation, the compound entries, the pending review items and the
    table-cell molecule tokens. Nothing is written and no choice is made.
    """
    empty = {
        "doc_id": doc_id,
        "summary": {
            "readings": 0,
            "attributed_readings": 0,
            "unattributed_readings": 0,
            "designations": 0,
            "candidate_structures": 0,
            "review_items": 0,
            "table_cells": 0,
            "names": 0,
        },
        "designations": [],
        "readings": [],
        "review_items": [],
        "table_cells": [],
        "names": [],
        "total": 0,
    }
    if not doc_id:
        return empty

    readings = list_activity_records(library_root, doc_id, limit=_READING_LIMIT)
    structures = _candidate_structures(library_root, doc_id)
    entries = _entries(library_root, doc_id)
    review_items = _review_items(library_root, doc_id)
    table_cells = _table_cells(library_root, doc_id)

    by_key: dict[str, list[dict[str, Any]]] = {}
    for structure in structures:
        for key in structure.get("label_keys") or []:
            by_key.setdefault(str(key), []).append(structure)

    index = _designation_index(readings, structures, entries)

    # Designations a reading needs to place come first: they are the decisions,
    # the rest is context the document printed without an activity.
    ordered = sorted(index, key=lambda key: (not index[key]["has_reading"], key))
    designations: list[dict[str, Any]] = []
    for key in ordered:
        item = index[key]
        key_readings = [
            reading
            for reading in readings
            if str(reading.get("reference_key") or "").strip() == key
        ]
        attribution = next(
            (
                _attribution(reading)
                for reading in key_readings
                if _attribution(reading) is not None
            ),
            None,
        )
        designations.append(
            {
                "label_key": item["label_key"],
                "label_raw": item["label_raw"],
                "reference_types": item["reference_types"],
                "pages": [page for page in item["pages"] if page is not None],
                "context_types": item["context_types"],
                "reading_ids": item["reading_ids"],
                "has_reading": item["has_reading"],
                "candidates": [_candidate_ref(row, key) for row in by_key.get(key, [])],
                "attribution": attribution,
            }
        )

    total = len(designations)
    page_rows = designations[offset : offset + limit] if limit > 0 else []
    attributed = sum(1 for reading in readings if reading.get("attributed"))
    return {
        "doc_id": doc_id,
        "summary": {
            "readings": len(readings),
            "attributed_readings": attributed,
            "unattributed_readings": len(readings) - attributed,
            "designations": total,
            "candidate_structures": len(structures),
            "review_items": len(review_items),
            "table_cells": len(table_cells),
            # Name → structure is a declared TODO: the package reserves the slot
            # so a caller can tell "no names" from "names not collected yet".
            "names": 0,
        },
        "designations": page_rows,
        "readings": [_reading_ref(reading) for reading in readings],
        "review_items": review_items,
        "table_cells": table_cells,
        "names": [],
        "total": total,
    }


__all__ = ["binding_candidates"]

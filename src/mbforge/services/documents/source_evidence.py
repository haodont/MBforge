"""Queries for the canonical document source-evidence table."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ...core.evidence import SourceEvidence, _normalise_bbox
from ...storage.sqlite.database import DatabaseManager
from ...utils.errors import NotFoundError, ValidationError
from .backup import create_backup

_COLUMNS = (
    "evidence_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1, "
    "raw_text, coref, kind"
)


def _row_to_evidence(row) -> SourceEvidence:  # type: ignore[no-untyped-def]
    return SourceEvidence.from_dict(
        {
            "evidence_id": row["evidence_id"],
            "doc_id": row["doc_id"],
            "page": row["page"],
            "bbox": [
                row["bbox_x0"],
                row["bbox_y0"],
                row["bbox_x1"],
                row["bbox_y1"],
            ],
            "raw_text": row["raw_text"],
            "coref": row["coref"],
            "kind": row["kind"],
        }
    )


def resolve(library_root: str | Path, evidence_id: str) -> SourceEvidence | None:
    """Resolve one canonical evidence ID to its immutable source object."""
    if not evidence_id:
        return None
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM source_evidence WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
    return _row_to_evidence(row) if row is not None else None


def list_evidence(
    library_root: str | Path,
    doc_id: str,
    page: int | None = None,
    kind: str | None = None,
) -> list[SourceEvidence]:
    """Load one document's source evidence in one SQL query.

    ``page`` and ``kind`` are optional filters for page/layout readers; the
    returned objects always come from SQLite rather than the JSON snapshot.
    """
    if not doc_id:
        return []
    if page is not None and (
        not isinstance(page, int) or isinstance(page, bool) or page < 1
    ):
        raise ValueError("page must be a positive 1-based integer")
    clauses = ["doc_id = ?"]
    params: list[object] = [doc_id]
    if page is not None:
        clauses.append("page = ?")
        params.append(page)
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM source_evidence WHERE {' AND '.join(clauses)} "
            "ORDER BY page, bbox_y1 DESC, bbox_x0, bbox_y0, bbox_x1, evidence_id",
            params,
        ).fetchall()
    return [_row_to_evidence(row) for row in rows]


def at(
    library_root: str | Path,
    doc_id: str,
    page: int,
    bbox: tuple[float, float, float, float] | list[float],
) -> list[SourceEvidence]:
    """Return all source evidence whose bbox intersects ``bbox``."""
    if not doc_id:
        return []
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("page must be a positive 1-based integer")
    x0, y0, x1, y1 = _normalise_bbox(bbox)
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM source_evidence "
            "WHERE doc_id = ? AND page = ? "
            "AND bbox_x1 >= ? AND bbox_x0 <= ? "
            "AND bbox_y1 >= ? AND bbox_y0 <= ? "
            "ORDER BY bbox_y1 DESC, bbox_x0, bbox_y0, bbox_x1, evidence_id",
            (doc_id, page, x0, x1, y0, y1),
        ).fetchall()
    return [_row_to_evidence(row) for row in rows]


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def find_text(
    library_root: str | Path, doc_id: str, query: str
) -> list[SourceEvidence]:
    """Return source evidence containing ``query`` after whitespace folding."""
    needle = _normalise_text(query)
    if not doc_id or not needle:
        return []
    return [
        evidence
        for evidence in list_evidence(library_root, doc_id)
        if needle in _normalise_text(evidence.raw_text)
    ]


def update_molecule(
    library_root: str | Path,
    doc_id: str,
    evidence_id: str,
    name: str,
    smiles: str,
) -> str:
    """Update editable molecule metadata while preserving the evidence ID."""
    name = name.strip()
    smiles = smiles.strip()
    if not doc_id or not evidence_id:
        raise ValidationError("doc_id and evidence_id are required")
    if not smiles:
        raise ValidationError("smiles is required")

    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT kind, raw_text FROM source_evidence "
            "WHERE evidence_id = ? AND doc_id = ?",
            (evidence_id, doc_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("source evidence not found", detail=evidence_id)
    if row["kind"] != "molecule":
        raise ValidationError("source evidence is not a molecule")

    try:
        metadata = json.loads(row["raw_text"] or "")
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {"raw_text": row["raw_text"] or ""}
    metadata["name"] = name
    metadata["smiles"] = smiles
    metadata["esmiles"] = smiles
    metadata["moldet_conf"] = 1.0

    create_backup(library_root, doc_id, "evidence_update")
    with db.mol_conn() as conn:
        cursor = conn.execute(
            "UPDATE source_evidence SET raw_text = ? "
            "WHERE evidence_id = ? AND doc_id = ? AND kind = 'molecule'",
            (
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                evidence_id,
                doc_id,
            ),
        )
        if cursor.rowcount != 1:
            raise NotFoundError("source evidence not found", detail=evidence_id)
    return evidence_id


__all__ = ["at", "find_text", "list_evidence", "resolve", "update_molecule"]

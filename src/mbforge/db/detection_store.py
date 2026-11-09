"""SQLite I/O for the interactive detection cache (``molecule_detections``).

This module owns only the cached detection rows: load/save per document and
page, the cache counters, and clearing.  Molecule CRUD lives in
``molecule_store``; candidate publication lives in ``molecule_candidates``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.db.detection_store")


def load_detections(
    library_root: str | Path, doc_id: str, page: int | None = None
) -> list[dict[str, Any]]:
    """Return ``molecule_detections`` rows for a document (all pages or one)."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    try:
        with db.mol_conn() as conn:
            if page is None:
                rows = conn.execute(
                    "SELECT * FROM molecule_detections WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM molecule_detections WHERE doc_id = ? AND page = ?",
                    (doc_id, page),
                ).fetchall()
    except Exception as exc:  # noqa: BLE001 - fresh library may lack the table
        logger.debug("load detections failed: %s", exc)
        return []
    return [dict(row) for row in rows]


def save_detections(
    library_root: str | Path, detections: Sequence[dict[str, Any]]
) -> None:
    """Insert/replace interactive detection rows (``molecule_detections``)."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.mol_conn() as conn:
        for det in detections:
            mol_id = det.get("mol_id")
            if mol_id:
                # molecule_detections.mol_id FK-references molecules(mol_id);
                # FE sends a display name, so keep it only if it is a real row.
                exists = conn.execute(
                    "SELECT 1 FROM molecules WHERE mol_id = ?", (mol_id,)
                ).fetchone()
                if not exists:
                    mol_id = None
            conn.execute(
                "INSERT OR REPLACE INTO molecule_detections "
                "(mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1, "
                "crop_relpath, conf_moldet, vlm_verified_esmiles) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mol_id,
                    det.get("doc_id"),
                    det.get("page"),
                    det.get("bbox_x0"),
                    det.get("bbox_y0"),
                    det.get("bbox_x1"),
                    det.get("bbox_y1"),
                    det.get("crop_relpath"),
                    det.get("conf_moldet"),
                    det.get("vlm_verified_esmiles")
                    or det.get("esmiles")
                    or det.get("smiles"),
                ),
            )


def detection_counts(library_root: str | Path) -> tuple[int, int]:
    """Return ``(cached_page_count, cached_doc_count)`` for the detection cache."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS page_count, "
            "COUNT(DISTINCT doc_id) AS doc_count "
            "FROM molecule_detections"
        ).fetchone()
    if row is None:
        return 0, 0
    return int(row["page_count"]), int(row["doc_count"])


def clear_detections(library_root: str | Path, doc_id: str | None = None) -> int:
    """Delete cached detections (one document, or all); return row count."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.mol_conn() as conn:
        if doc_id is None:
            cursor = conn.execute("DELETE FROM molecule_detections")
        else:
            cursor = conn.execute(
                "DELETE FROM molecule_detections WHERE doc_id = ?", (doc_id,)
            )
        return int(cursor.rowcount)


__all__ = [
    "clear_detections",
    "detection_counts",
    "load_detections",
    "save_detections",
]

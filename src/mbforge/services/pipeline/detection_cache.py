"""Detection cache service — ``molecule_detections`` table access.

All reads and writes for the detection cache (FE surface for read / clear /
stats, plus cache-aware single-page reads) go through here. Logic ported from
``legacy_models.py`` (2026-07-14).
"""

from __future__ import annotations

from typing import Any

from ...storage.sqlite.database import DatabaseManager
from ...utils.logger import get_logger

logger = get_logger(__name__)


def _row_to_result(row: Any) -> dict[str, Any]:
    """Map molecule_detections row → ExtractionResult-shaped dict."""
    moldet_conf = row["conf_moldet"] or 0.0
    return {
        "esmiles": row["vlm_verified_esmiles"] or "",
        "name": row["mol_id"] or "",
        "source": "image",
        "moldet_conf": moldet_conf,
        "bbox_pdf": [
            row["bbox_x0"] or 0.0,
            row["bbox_y0"] or 0.0,
            row["bbox_x1"] or 0.0,
            row["bbox_y1"] or 0.0,
        ],
        "page_idx": row["page"],
        "context_text": "",
        "mol_img_path": row["crop_relpath"],
        "status": "pending",
        "properties": {},
        # keep raw fields for callers that still expect SQL shape
        "mol_id": row["mol_id"],
        "doc_id": row["doc_id"],
        "page": row["page"],
        "bbox_x0": row["bbox_x0"],
        "bbox_y0": row["bbox_y0"],
        "bbox_x1": row["bbox_x1"],
        "bbox_y1": row["bbox_y1"],
        "crop_relpath": row["crop_relpath"],
        "conf_moldet": row["conf_moldet"],
    }


def load_cached_detections(library_root: str, doc_id: str, page: int) -> dict[str, Any]:
    db = DatabaseManager.get(library_root)
    db.initialize()
    rows: list[Any] = []
    try:
        with db.mol_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM molecule_detections WHERE doc_id = ? AND page = ?",
                (doc_id, page),
            ).fetchall()
    except Exception as e:  # noqa: BLE001 - fresh library may lack table yet
        logger.debug("load detections failed: %s", e)
        rows = []

    results = [_row_to_result(r) for r in rows]
    return {
        "success": True,
        "results": results,
        "detections": results,  # back-compat alias
        "count": len(results),
        "source": "cache" if results else "cache_miss",
    }


def load_all_cached_detections(library_root: str, doc_id: str) -> list[dict[str, Any]]:
    """Return every interactive ``molecule_detections`` row for *doc_id*.

    Document-level counterpart of :func:`load_cached_detections` — one query
    for all pages so the PDF viewer can prime its whole overlay in a single
    request instead of one query per page turn.
    """
    db = DatabaseManager.get(library_root)
    db.initialize()
    rows: list[Any] = []
    try:
        with db.mol_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM molecule_detections WHERE doc_id = ?",
                (doc_id,),
            ).fetchall()
    except Exception as e:  # noqa: BLE001 - fresh library may lack table yet
        logger.debug("load all detections failed: %s", e)
        rows = []
    return [_row_to_result(r) for r in rows]


def save_detections(library_root: str, detections: list[dict]) -> None:
    db = DatabaseManager.get(library_root)
    db.initialize()
    with db.mol_conn() as conn:
        for det in detections:
            mol_id = det.get("mol_id")
            if mol_id:
                # molecule_detections.mol_id FK-references molecules(mol_id);
                # FE sends a display name, so keep it only if it is a real row.
                exists = conn.execute(
                    "SELECT 1 FROM molecules WHERE mol_id = ?",
                    (mol_id,),
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


def read_stats(library_root: str) -> dict[str, Any]:
    db = DatabaseManager.get(library_root)
    db.initialize()
    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS page_count, "
            "COUNT(DISTINCT doc_id) AS doc_count "
            "FROM molecule_detections"
        ).fetchone()
    return {
        "disk_usage_bytes": 0,
        "cached_page_count": row["page_count"] if row else 0,
        "cached_doc_count": row["doc_count"] if row else 0,
        "schema_version": 1,
    }


def clear_all(library_root: str) -> int:
    db = DatabaseManager.get(library_root)
    db.initialize()
    with db.mol_conn() as conn:
        cur = conn.execute("DELETE FROM molecule_detections")
        return cur.rowcount


def clear_doc(library_root: str, doc_id: str) -> int:
    db = DatabaseManager.get(library_root)
    db.initialize()
    with db.mol_conn() as conn:
        cur = conn.execute(
            "DELETE FROM molecule_detections WHERE doc_id = ?",
            (doc_id,),
        )
        return cur.rowcount

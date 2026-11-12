"""Persistence for the ADR 0001 ``label_anchor`` index and page geometry.

Overwrite policy
----------------
Anchors are a producer projection of the canonical evidence, not an append-only
assertion log (that is ``relation_pair``). A re-extract therefore refreshes the
document's whole anchor set and page geometry in one transaction: delete by
``doc_id``, then insert the new batch. ``anchor_id`` is content-derived
(``stable_id("anchor", doc, evidence, label_key, occurrence)``), so an unchanged
re-extract reproduces identical ids.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.relation import LabelAnchor, PageGeometry
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.db.label_anchor")


def persist_label_anchors(
    library_root: str | Path,
    doc_id: str,
    anchors: Sequence[LabelAnchor],
    geometry: Sequence[PageGeometry] = (),
) -> int:
    """Replace one document's anchor index and page geometry; return the count."""
    items = list(anchors)
    pages = list(geometry)
    if any(item.doc_id != doc_id for item in items):
        raise ValueError("label anchor batch contains a different doc_id")
    if any(page.doc_id != doc_id for page in pages):
        raise ValueError("page geometry batch contains a different doc_id")
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.connection() as conn:
        conn.execute("DELETE FROM label_anchor WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM page_geometry WHERE doc_id = ?", (doc_id,))
        for page in pages:
            conn.execute(
                "INSERT INTO page_geometry "
                "(doc_id, page, width_pt, height_pt, render_dpi, quality_class) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    page.doc_id,
                    page.page,
                    page.width_pt,
                    page.height_pt,
                    page.render_dpi,
                    page.quality_class,
                ),
            )
        for item in items:
            x0, y0, x1, y1 = item.bbox
            conn.execute(
                "INSERT INTO label_anchor "
                "(anchor_id, doc_id, evidence_id, page, bbox_x0, bbox_y0, "
                "bbox_x1, bbox_y1, label_raw, label_key, key_space, anchor_kind, "
                "source, occurrence, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.anchor_id,
                    item.doc_id,
                    item.evidence_id,
                    item.page,
                    x0,
                    y0,
                    x1,
                    y1,
                    item.label_raw,
                    item.label_key,
                    item.key_space,
                    item.anchor_kind,
                    item.source,
                    item.occurrence,
                    item.confidence,
                ),
            )
    return len(items)


def anchor_coverage(
    library_root: str | Path, doc_id: str | None = None
) -> dict[str, object]:
    """Count anchors by key space, kind and source — the coverage metric.

    ``doc_id`` narrows to one document; omit for the whole library. The counts
    answer "how many printed designations have an anchor, in which space",
    which is the association headroom the ADR makes measurable.
    """
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    where = ""
    params: list[object] = []
    if doc_id:
        where = " WHERE doc_id = ?"
        params.append(doc_id)
    with db.connection() as conn:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM label_anchor{where}", params
            ).fetchone()[0]
        )
        documents = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT doc_id) FROM label_anchor{where}", params
            ).fetchone()[0]
        )
        distinct_labels = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT label_key) FROM label_anchor{where}", params
            ).fetchone()[0]
        )

        def grouped(column: str) -> dict[str, int]:
            rows = conn.execute(
                f"SELECT {column}, COUNT(*) FROM label_anchor{where} GROUP BY {column}",
                params,
            ).fetchall()
            return {str(row[0]): int(row[1]) for row in rows}

        return {
            "anchors": total,
            "documents": documents,
            "distinct_labels": distinct_labels,
            "by_key_space": grouped("key_space"),
            "by_anchor_kind": grouped("anchor_kind"),
            "by_source": grouped("source"),
        }


__all__ = ["anchor_coverage", "persist_label_anchors"]

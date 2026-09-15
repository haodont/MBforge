"""Persistence for the canonical document source-evidence index.

Overwrite policy
----------------
``evidence_id`` is derived from the geometric location
(``doc_id`` / ``page`` / ``kind`` / rounded bbox), so re-detecting the same
region reproduces the same id while the payload (compound label, SMILES,
confidence) may legitimately change.  A changed payload is therefore allowed
to overwrite the stored row, but only through an explicit
``DELETE`` by ``evidence_id`` followed by an ``INSERT`` of the new content in
the same transaction: the id is never re-pointed, so downstream references
stay valid, and no ``UPDATE`` can leave a half-refreshed row behind.

A batch may still not *drop* evidence ids that already exist for the
document.  Stale rows are reported instead of being silently rewritten, see
:func:`persist_source_evidence`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from mbforge.utils.logger import get_logger

from .sqlite.database import DatabaseManager

if TYPE_CHECKING:
    from mbforge.core.evidence import SourceEvidence

logger = get_logger("mbforge.storage.source_evidence")

# Column order of the immutability probe below; used for change reporting.
_PROBE_FIELDS = (
    "doc_id",
    "page",
    "bbox_x0",
    "bbox_y0",
    "bbox_x1",
    "bbox_y1",
    "raw_text",
    "coref",
    "kind",
)


def _changed_fields(
    stored: tuple[object, ...] | list[object], incoming: tuple[object, ...]
) -> list[str]:
    """Name the probe columns whose stored value differs from the incoming one."""
    return [
        name
        for name, old, new in zip(_PROBE_FIELDS, stored, incoming, strict=False)
        if old != new
    ]


def persist_source_evidence(
    library_root: str | Path,
    evidence: Sequence[SourceEvidence] | object,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Insert the complete joined source-evidence batch in one transaction.

    Rows whose geometry-keyed ``evidence_id`` already exists are refreshed
    (deleted by ``evidence_id``, then inserted again) when their content
    changed, and left untouched when it did not.  Returns the number of
    persisted rows.
    """
    expected_doc_id = getattr(evidence, "doc_id", None)
    if not isinstance(evidence, Sequence):
        evidence = getattr(evidence, "evidence", ())
    items = list(evidence)
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    connection = nullcontext(conn) if conn is not None else db.mol_conn()
    count = 0
    refreshed = 0
    with connection as active_conn:
        if active_conn is None:
            raise RuntimeError("No database connection available")
        if expected_doc_id is None and items:
            expected_doc_id = items[0].doc_id
        if any(item.doc_id != expected_doc_id for item in items):
            raise ValueError("source evidence batch contains multiple doc_ids")
        batch_ids = {item.evidence_id for item in items}
        existing_ids = {
            row[0]
            for row in active_conn.execute(
                "SELECT evidence_id FROM source_evidence WHERE doc_id = ?",
                (expected_doc_id,),
            ).fetchall()
        }
        stale_ids = existing_ids - batch_ids
        if stale_ids:
            raise ValueError(
                "source evidence batch is immutable: it would drop "
                f"{len(stale_ids)} existing id(s), e.g. {sorted(stale_ids)[:3]}"
            )
        for item in items:
            if not item.doc_id:
                raise ValueError(f"source evidence has no doc_id: {item.evidence_id}")
            if expected_doc_id is not None and item.doc_id != expected_doc_id:
                raise ValueError(
                    f"source evidence has wrong doc_id: {item.evidence_id}"
                )
            x0, y0, x1, y1 = item.bbox
            values = (
                item.evidence_id,
                item.doc_id,
                item.page,
                x0,
                y0,
                x1,
                y1,
                item.raw_text,
                item.coref,
                item.kind,
            )
            existing = active_conn.execute(
                "SELECT doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1, "
                "raw_text, coref, kind FROM source_evidence "
                "WHERE evidence_id = ?",
                (item.evidence_id,),
            ).fetchone()
            if existing is not None:
                stored = tuple(existing)
                if stored == values[1:]:
                    count += 1
                    continue
                # 覆写：先按 evidence_id 删除旧行，再在同一事务内写入新内容。
                # evidence_id 保持不变，因此下游引用（molecules / activities）
                # 无需重建；created_at 会随重新插入刷新。
                active_conn.execute(
                    "DELETE FROM source_evidence WHERE evidence_id = ?",
                    (item.evidence_id,),
                )
                logger.info(
                    "Refreshed source evidence %s (doc=%s page=%s kind=%s): %s",
                    item.evidence_id,
                    item.doc_id,
                    item.page,
                    item.kind,
                    ", ".join(_changed_fields(stored, values[1:])) or "unknown",
                )
                refreshed += 1
            active_conn.execute(
                "INSERT INTO source_evidence "
                "(evidence_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1, "
                "raw_text, coref, kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            count += 1
    if refreshed:
        logger.warning(
            "Overwrote %d source evidence row(s) for %s (deleted and re-inserted "
            "under the same evidence_id)",
            refreshed,
            expected_doc_id,
        )
    return count


__all__ = ["persist_source_evidence"]

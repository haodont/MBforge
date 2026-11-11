"""SQLite data access for printed activity readings and their attributions.

``measurements`` stores a reading exactly as the document printed it. It has no
structural requirement and no ``mol_id``: a reading that no structure owns is
still a citable fact, and dropping it is what made the previous design lossy.
``measurement_attribution`` carries the optional ``reading -> structure`` links.

Both tables are document-scoped: every write deletes the document's rows first,
so a re-run replaces instead of duplicating.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mbforge.contracts.measurement import (
    MeasurementAttribution,
    MeasurementDatasetStats,
    MeasurementQuery,
    MeasurementRecord,
)
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.foundation.ids import stable_id

_MEASUREMENT_COLUMNS: tuple[str, ...] = (
    "measurement_id",
    "doc_id",
    "entry_id",
    "assay_method_id",
    "metric",
    "activity_type",
    "measurement_kind",
    "original_value",
    "original_unit",
    "canonical_value",
    "canonical_unit",
    "operator",
    "scale",
    "value_text",
    "qualitative_raw",
    "qualitative_rank",
    "qualitative_scheme",
    "qualitative_label",
    "target",
    "species",
    "assay_type",
    "assay_description",
    "raw_text",
    "page_num",
    "table_idx",
    "row_idx",
    "col_idx",
    "row_label",
    "reference_raw",
    "reference_key",
    "reference_type",
    "evidence_ids",
    "provenance",
    "evidence_grade",
    "review_status",
    "linking_status",
    "run_id",
)

_JSON_COLUMNS = ("evidence_ids", "provenance")


def _row_to_measurement(row: Any) -> dict[str, Any]:
    """Project a measurements row, decoding its JSON columns."""
    data = dict(row)
    for column in _JSON_COLUMNS:
        raw = data.get(column)
        default: Any = [] if column == "evidence_ids" else {}
        try:
            decoded = json.loads(raw) if isinstance(raw, str) else (raw or default)
        except json.JSONDecodeError:
            decoded = default
        if not isinstance(decoded, type(default)):
            decoded = default
        data[column] = decoded
    return data


def insert_measurements_in_transaction(
    conn: Any, records: Sequence[MeasurementRecord]
) -> int:
    """Insert *records* on *conn*; the caller owns the transaction.

    ``measurement_id`` is deterministic (doc + page + metric + raw value + row
    label), so ``INSERT OR REPLACE`` makes a re-run idempotent, not additive.
    """
    columns = ", ".join(_MEASUREMENT_COLUMNS)
    placeholders = ", ".join("?" for _ in _MEASUREMENT_COLUMNS)
    written = 0
    for record in records:
        payload = record.model_dump()
        values: list[Any] = []
        for column in _MEASUREMENT_COLUMNS:
            value = payload.get(column)
            if column in _JSON_COLUMNS:
                value = json.dumps(value, ensure_ascii=False)
            values.append(value)
        conn.execute(
            f"INSERT OR REPLACE INTO measurements ({columns}) VALUES ({placeholders})",
            values,
        )
        written += 1
    return written


def insert_attributions_in_transaction(
    conn: Any, attributions: Sequence[MeasurementAttribution]
) -> int:
    """Insert *attributions* on *conn*; the caller owns the transaction."""
    written = 0
    for attribution in attributions:
        payload = attribution.model_dump()
        conn.execute(
            """
            INSERT OR REPLACE INTO measurement_attribution
                (attribution_id, measurement_id, mol_id, doc_id, method,
                 confidence, evidence_id, review_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["attribution_id"],
                payload["measurement_id"],
                payload["mol_id"],
                payload["doc_id"],
                payload["method"],
                payload["confidence"],
                payload["evidence_id"],
                payload["review_status"],
            ),
        )
        written += 1
    return written


def replace_document_measurements(
    library_root: str | Path,
    doc_id: str,
    records: Sequence[MeasurementRecord],
    attributions: Sequence[MeasurementAttribution] = (),
) -> int:
    """Replace one document's readings and attributions in one transaction."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.transaction() as (_kb_conn, conn):
        delete_document_measurements(conn, doc_id)
        written = insert_measurements_in_transaction(conn, records)
        insert_attributions_in_transaction(conn, attributions)
    return written


def list_measurements(
    library_root: str | Path, query: MeasurementQuery
) -> list[dict[str, Any]]:
    """Read readings for a document, optionally filtered, in document order."""
    db = DatabaseManager.get(str(library_root))
    clauses: list[str] = []
    params: list[Any] = []
    if query.doc_id:
        clauses.append("doc_id = ?")
        params.append(query.doc_id)
    if query.target:
        clauses.append("LOWER(COALESCE(target, '')) LIKE ?")
        params.append(f"%{query.target.lower()}%")
    if query.assay_description:
        clauses.append("LOWER(COALESCE(assay_description, assay_type, '')) LIKE ?")
        params.append(f"%{query.assay_description.lower()}%")
    if query.evidence_grade:
        clauses.append("evidence_grade = ?")
        params.append(query.evidence_grade)
    if query.review_status:
        clauses.append("review_status = ?")
        params.append(query.review_status)
    if query.metric:
        clauses.append("LOWER(COALESCE(metric, '')) = ?")
        params.append(query.metric.lower())
    if query.min_value is not None:
        clauses.append("canonical_value IS NOT NULL AND canonical_value >= ?")
        params.append(query.min_value)
    if query.max_value is not None:
        clauses.append("canonical_value IS NOT NULL AND canonical_value <= ?")
        params.append(query.max_value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT * FROM measurements {where} "
        "ORDER BY page_num, table_idx, row_idx, col_idx, measurement_id "
        "LIMIT ? OFFSET ?"
    )
    params.extend((query.limit, query.offset))
    with db.mol_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_measurement(row) for row in rows]


def list_attributions_for(
    library_root: str | Path, measurement_ids: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    """Return ``measurement_id -> attribution rows`` for the given readings."""
    ids = [item for item in measurement_ids if item]
    if not ids:
        return {}
    db = DatabaseManager.get(str(library_root))
    result: dict[str, list[dict[str, Any]]] = {}
    with db.mol_conn() as conn:
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                "SELECT * FROM measurement_attribution "
                f"WHERE measurement_id IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                result.setdefault(row["measurement_id"], []).append(dict(row))
    return result


def dataset_stats(
    library_root: str | Path, doc_id: str = ""
) -> MeasurementDatasetStats:
    """Count readings and attributions so the extraction backlog is measurable."""
    db = DatabaseManager.get(str(library_root))
    scope = "WHERE doc_id = ?" if doc_id else ""
    params: tuple[Any, ...] = (doc_id,) if doc_id else ()
    joined_scope = "WHERE m.doc_id = ?" if doc_id else ""
    pending_scope = (
        "WHERE doc_id = ? AND review_status = 'pending'"
        if doc_id
        else "WHERE review_status = 'pending'"
    )
    with db.mol_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM measurements {scope}", params
        ).fetchone()["c"]
        attributed = conn.execute(
            "SELECT COUNT(DISTINCT m.measurement_id) AS c FROM measurements m "
            "JOIN measurement_attribution a ON a.measurement_id = m.measurement_id "
            f"{joined_scope}",
            params,
        ).fetchone()["c"]
        pending = conn.execute(
            f"SELECT COUNT(*) AS c FROM measurements {pending_scope}", params
        ).fetchone()["c"]
        by_target = {
            (row["target"] or ""): row["c"]
            for row in conn.execute(
                f"SELECT target, COUNT(*) AS c FROM measurements {scope} "
                "GROUP BY target",
                params,
            )
        }
        by_assay = {
            (row["assay"] or ""): row["c"]
            for row in conn.execute(
                "SELECT COALESCE(assay_description, assay_type) AS assay, "
                f"COUNT(*) AS c FROM measurements {scope} GROUP BY assay",
                params,
            )
        }
    return MeasurementDatasetStats(
        total=total,
        attributed=attributed,
        unattributed=total - attributed,
        pending_review=pending,
        by_target=by_target,
        by_assay=by_assay,
    )


def unattributed_readings(
    library_root: str | Path, doc_id: str = ""
) -> list[dict[str, Any]]:
    """Return every reading, with its designation number and attribution state.

    The DB layer stays free of the pipeline's classification rules; it reports
    the facts a classifier needs — the printed designation's number and whether
    any structure is attached — and lets the service decide why.
    """
    db = DatabaseManager.get(str(library_root))
    scope = "WHERE m.doc_id = ?" if doc_id else ""
    params: tuple[Any, ...] = (doc_id,) if doc_id else ()
    with db.mol_conn() as conn:
        rows = conn.execute(
            "SELECT m.measurement_id, m.doc_id, m.entry_id, m.reference_key, "
            "a.measurement_id AS attributed_id "
            f"FROM measurements m LEFT JOIN measurement_attribution a "
            "ON a.measurement_id = m.measurement_id "
            f"{scope}",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def bind_attribution(
    library_root: str | Path,
    *,
    measurement_id: str,
    mol_id: str,
    doc_id: str,
    evidence_id: str = "",
    method: str = "human",
) -> str:
    """Record one accepted reading -> structure link and return its id.

    This is the human decision path: a review item names the reading and the
    chosen structure, and the attribution row is written here with the method that
    produced it, so a human link is never indistinguishable from a rule link.
    """
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    attribution_id = stable_id("attr", measurement_id, mol_id, method)
    with db.transaction() as (_kb_conn, conn):
        conn.execute(
            "INSERT OR REPLACE INTO measurement_attribution "
            "(attribution_id, measurement_id, mol_id, doc_id, method, "
            " confidence, evidence_id, review_status) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, 'accepted')",
            (
                attribution_id,
                measurement_id,
                mol_id,
                doc_id,
                method,
                evidence_id or None,
            ),
        )
        conn.execute(
            "UPDATE measurements SET review_status = 'accepted' "
            "WHERE measurement_id = ?",
            (measurement_id,),
        )
    return attribution_id


def unlabeled_structure_count(library_root: str | Path, doc_id: str) -> int:
    """Structures this document drew whose printed designation was not read.

    ``dataset_stats`` uses it to tell "the label was never read" (recoverable)
    apart from "the document drew no such structure" (a source fact).
    """
    if not doc_id:
        return 0
    db = DatabaseManager.get(str(library_root))
    rows = db.execute(
        "SELECT COUNT(*) AS c FROM molecules "
        "WHERE source_doc = ? AND TRIM(COALESCE(name, '')) = ''",
        (doc_id,),
        db="mol",
    )
    return int(rows[0]["c"]) if rows else 0


def delete_document_measurements(conn: Any, doc_id: str) -> None:
    """Delete one document's readings and attributions on *conn*."""
    conn.execute("DELETE FROM measurement_attribution WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM measurements WHERE doc_id = ?", (doc_id,))


__all__ = [
    "bind_attribution",
    "dataset_stats",
    "delete_document_measurements",
    "insert_attributions_in_transaction",
    "insert_measurements_in_transaction",
    "list_attributions_for",
    "list_measurements",
    "replace_document_measurements",
    "unattributed_readings",
    "unlabeled_structure_count",
]

"""SQLite data access for the molecule catalog.

Owns every query the molecule use cases need (list, get, create, update,
delete, stats, search, corrections, detection-cache lookup) so the service
layer never executes SQL.  Functions return raw row dicts; the service layer
normalizes and shapes them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rdkit import Chem

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.molecule import Molecule
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.db.molecule_store")

_MAX_MATCHING_IDS = 1000
_MAX_FILTER_OPTIONS = 1000


def list_page(library_root: str | Path, request: Any) -> dict[str, Any]:
    """Run the molecule list query (filters, counts, filter options).

    *request* is the ``MoleculeListRequest`` DTO.  Returns a plain dict with
    ``rows`` / ``total`` / ``matching_ids`` / ``truncated`` / ``source_types`` /
    ``source_docs`` so the service layer can assemble the response.
    """
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        where_parts = ["1=1"]
        params: list[Any] = []
        if request.status:
            where_parts.append("status = ?")
            params.append(request.status)
        if request.source_type:
            where_parts.append("source_type = ?")
            params.append(request.source_type)
        if request.source_doc:
            where_parts.append(
                "(source_doc = ? OR EXISTS ("
                "SELECT 1 FROM evidence e WHERE e.doc_id = ? AND "
                "(e.mol_id = molecules.mol_id OR "
                "e.canonical_smiles = molecules.canonical_smiles)))"
            )
            params.extend([request.source_doc, request.source_doc])
        if request.activity_presence == "present":
            where_parts.append("activity IS NOT NULL")
        elif request.activity_presence == "missing":
            where_parts.append("activity IS NULL")
        if request.activity_min is not None:
            where_parts.append("activity IS NOT NULL AND activity >= ?")
            params.append(request.activity_min)
        if request.activity_max is not None:
            where_parts.append("activity IS NOT NULL AND activity <= ?")
            params.append(request.activity_max)
        if request.query.strip():
            query = f"%{request.query.strip()}%"
            where_parts.append(
                "(mol_id LIKE ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE "
                "OR notes LIKE ? COLLATE NOCASE OR source_doc LIKE ? COLLATE NOCASE "
                "OR smiles LIKE ? COLLATE NOCASE OR esmiles LIKE ? COLLATE NOCASE)"
            )
            params.extend([query] * 6)

        where = "WHERE " + " AND ".join(where_parts)
        sort_columns = {
            "name": "name",
            "activity": "activity",
            "status": "status",
            "created_at": "created_at",
        }
        sort_column = sort_columns.get(request.sort_field, "created_at")
        direction = "ASC" if request.sort_direction == "asc" else "DESC"
        nulls_last = "activity IS NULL ASC, " if sort_column == "activity" else ""
        order_by = f"{nulls_last}{sort_column} {direction}, mol_id ASC"

        total = conn.execute(
            f"SELECT COUNT(*) FROM molecules {where}", params
        ).fetchone()[0]

        # Cap matching_ids to keep list responses bounded; with 100k+ molecules
        # the full id list alone costs ~2MB and dominates the response.
        matching_id_rows = conn.execute(
            f"SELECT mol_id FROM molecules {where} ORDER BY {order_by} LIMIT ?",
            params + [_MAX_MATCHING_IDS + 1],
        ).fetchall()
        matching_truncated = len(matching_id_rows) > _MAX_MATCHING_IDS
        matching_ids = [r[0] for r in matching_id_rows[:_MAX_MATCHING_IDS]]

        offset = (request.page - 1) * request.page_size
        rows = conn.execute(
            f"SELECT * FROM molecules {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            params + [request.page_size, offset],
        ).fetchall()
        source_types = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT source_type FROM molecules "
                "WHERE source_type IS NOT NULL AND source_type != '' "
                "ORDER BY source_type LIMIT ?",
                (_MAX_FILTER_OPTIONS,),
            ).fetchall()
        ]
        source_docs = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT source_doc FROM molecules "
                "WHERE source_doc IS NOT NULL AND source_doc != '' "
                "ORDER BY source_doc LIMIT ?",
                (_MAX_FILTER_OPTIONS,),
            ).fetchall()
        ]
        source_docs.extend(
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT doc_id FROM evidence "
                "WHERE doc_id IS NOT NULL AND doc_id != '' "
                "ORDER BY doc_id LIMIT ?",
                (_MAX_FILTER_OPTIONS,),
            ).fetchall()
            if row[0] not in source_docs
        )
        source_docs.sort()
    return {
        "rows": [dict(row) for row in rows],
        "total": total,
        "matching_ids": matching_ids,
        "truncated": matching_truncated,
        "source_types": source_types,
        "source_docs": source_docs,
    }


def get_row(library_root: str | Path, mol_id: str) -> dict[str, Any] | None:
    """Return one ``molecules`` row by ``mol_id``, or ``None``."""
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT * FROM molecules WHERE mol_id = ?", (mol_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def find_row(library_root: str | Path, canonical_smiles: str) -> dict[str, Any] | None:
    """Return one ``molecules`` row by ``mol_id`` or ``canonical_smiles``."""
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT * FROM molecules WHERE mol_id = ? OR canonical_smiles = ?",
            (canonical_smiles, canonical_smiles),
        ).fetchone()
    return dict(row) if row is not None else None


def create(
    library_root: str | Path,
    mol_id: str,
    smiles: str,
    esmiles: str | None,
    name: str | None,
    source_type: str | None,
) -> None:
    """Insert or replace a molecule and refresh its search index."""
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        db.delete_molecule_from_mol_search(conn, mol_id)
        conn.execute(
            "INSERT OR REPLACE INTO molecules "
            "(mol_id, smiles, esmiles, name, source_type, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mol_id, smiles, esmiles, name, source_type, "active"),
        )
        db.sync_molecule_to_mol_search(conn, mol_id)
        db.sync_molecule_fingerprint(conn, mol_id)


def bulk_update_status(
    library_root: str | Path, mol_ids: Sequence[str], status: str
) -> int:
    """Set ``status`` for the given molecules; return the updated row count."""
    db = DatabaseManager.get(str(library_root))
    unique_ids = list(dict.fromkeys(mol_ids))
    placeholders = ",".join("?" for _ in unique_ids)
    with db.mol_conn() as conn:
        cursor = conn.execute(
            f"UPDATE molecules SET status = ? WHERE mol_id IN ({placeholders})",
            [status, *unique_ids],
        )
        return int(cursor.rowcount)


def update(library_root: str | Path, mol_id: str, updates: dict[str, Any]) -> None:
    """Apply column updates and record a SMILES correction when it changes.

    *updates* keys must be DB column names; list/dict values are stored as JSON
    text. Search-index and fingerprint tables are refreshed.
    """
    db = DatabaseManager.get(str(library_root))
    params: list[Any] = []
    for val in updates.values():
        if isinstance(val, (list, dict)):
            val = json.dumps(val)
        params.append(val)
    params.append(mol_id)
    with db.mol_conn() as conn:
        previous = conn.execute(
            "SELECT smiles FROM molecules WHERE mol_id = ?", (mol_id,)
        ).fetchone()
        new_smiles = updates.get("smiles")
        if new_smiles is not None and previous and previous[0] != new_smiles:
            conn.execute(
                """
                INSERT INTO molecule_corrections
                    (mol_id, field, old_value, new_value, source)
                VALUES (?, 'smiles', ?, ?, 'molecule_update')
                """,
                (mol_id, previous[0], new_smiles),
            )
        db.delete_molecule_from_mol_search(conn, mol_id)
        conn.execute(
            f"UPDATE molecules SET {', '.join(f'{k} = ?' for k in updates)} "
            "WHERE mol_id = ?",
            params,
        )
        db.sync_molecule_to_mol_search(conn, mol_id)


def list_corrections(library_root: str | Path, mol_id: str) -> list[dict[str, Any]]:
    """Return append-only manual corrections for a molecule."""
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            """
            SELECT correction_id, mol_id, field, old_value, new_value,
                   source, created_at
            FROM molecule_corrections
            WHERE mol_id = ?
            ORDER BY correction_id ASC
            """,
            (mol_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete(library_root: str | Path, mol_ids: Sequence[str]) -> int:
    """Delete molecules and their owned rows; return the deleted row count."""
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        return DatabaseManager.delete_molecule_records(conn, mol_ids)


def stats(library_root: str | Path) -> dict[str, Any]:
    """Return total plus per-status and per-source counts."""
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM molecules GROUP BY status"
        ).fetchall()
        by_source = conn.execute(
            "SELECT source_type, COUNT(*) as cnt FROM molecules GROUP BY source_type"
        ).fetchall()
    return {
        "total": total,
        "by_status": {r["status"]: r["cnt"] for r in by_status},
        "by_source": {r["source_type"]: r["cnt"] for r in by_source},
    }


def search_text(
    library_root: str | Path, query: str, top_k: int
) -> list[dict[str, Any]]:
    """FTS5 text search over molecule names/notes (literal, not query syntax)."""
    # FTS5 parses punctuation such as ``=`` as query syntax. User-entered
    # molecule names and notes must instead be searched as literal text.
    literal_query = f'"{query.replace('"', '""')}"'
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            "SELECT m.* FROM mol_search ms JOIN molecules m ON ms.rowid = m.rowid "
            "WHERE mol_search MATCH ? LIMIT ?",
            (literal_query, top_k),
        ).fetchall()
    return [dict(row) for row in rows]


def search_substructure(
    library_root: str | Path, query_smiles: str, top_k: int
) -> list[dict[str, Any]]:
    """Substructure search against the library database (blocking)."""
    query_mol = Chem.MolFromSmiles(query_smiles)
    if query_mol is None:
        return []
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM molecules "
            "WHERE fingerprint IS NOT NULL OR smiles IS NOT NULL"
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        smiles = row["canonical_smiles"] or row["smiles"]
        if not smiles:
            continue
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            continue
        if mol.HasSubstructMatch(query_mol):
            results.append(dict(row))
            if len(results) >= top_k:
                break
    return results


def search_similarity(
    library_root: str | Path, query_smiles: str, top_k: int, threshold: float
) -> list[dict[str, Any]]:
    """Similarity search against the library database (blocking)."""
    query_mol = Molecule(mol_id="", canonical_smiles=query_smiles)
    if query_mol.fingerprint is None:
        return []
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM molecules WHERE fingerprint IS NOT NULL"
        ).fetchall()
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        candidate_mol = Molecule.from_row(row)
        if candidate_mol.fingerprint is None:
            continue
        similarity = query_mol.similarity(candidate_mol)
        if similarity >= threshold:
            item = dict(row)
            item["similarity"] = similarity
            scored.append((similarity, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def detection_cache_matches(
    library_root: str | Path,
    doc_id: str,
    page: int,
    query_box: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Interactive detection-cache rows (``molecule_detections``).

    ``page`` is the public 1-based page; the stored column is 0-based, so the
    boundary converts once.  Returns match dicts shaped for the caller.
    """
    qx0, qy0, qx1, qy1 = query_box
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            """
            SELECT mol_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                   crop_relpath, conf_moldet,
                   vlm_verified_esmiles
            FROM molecule_detections
            WHERE doc_id = ? AND page = ?
              AND bbox_x0 <= ? AND bbox_x1 >= ?
              AND bbox_y0 <= ? AND bbox_y1 >= ?
            """,
            [doc_id, page - 1, qx0, qx1, qy0, qy1],
        ).fetchall()
    matches: list[dict[str, Any]] = []
    for row in rows:
        matches.append(
            {
                "mol_id": row["mol_id"],
                "canonical_smiles": row["mol_id"]
                or (row["vlm_verified_esmiles"] or ""),
                "doc_id": doc_id,
                "name": "",
                "confidence": row["conf_moldet"],
                "page": page,
                "bbox": {
                    "x0": row["bbox_x0"],
                    "y0": row["bbox_y0"],
                    "x1": row["bbox_x1"],
                    "y1": row["bbox_y1"],
                },
                "crop_relpath": row["crop_relpath"],
            }
        )
    return matches


def identity_fields(
    library_root: str | Path, mol_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Return ``{mol_id: {canonical_smiles, name}}`` for the given ids."""
    ids = sorted({mol_id for mol_id in mol_ids if mol_id})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            f"SELECT mol_id, canonical_smiles, name FROM molecules "
            f"WHERE mol_id IN ({placeholders})",
            ids,
        ).fetchall()
    return {
        row["mol_id"]: {
            "canonical_smiles": row["canonical_smiles"],
            "name": row["name"],
        }
        for row in rows
    }


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


def molecules_for_recorrection(
    library_root: str | Path, doc_id: str | None = None
) -> list[dict[str, Any]]:
    """Return the ``molecules`` rows to recorrect (all, or one document's)."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    if doc_id:
        query = (
            "SELECT DISTINCT m.* FROM molecules m "
            "JOIN molecule_detections md ON m.mol_id = md.mol_id "
            "WHERE md.doc_id = ?"
        )
        params: tuple[Any, ...] = (doc_id,)
    else:
        query = "SELECT * FROM molecules"
        params = ()
    rows = db.execute(query, params, db="mol")
    return [dict(row) for row in rows]


def detections_for_molecules(
    library_root: str | Path, mol_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """Return every ``molecule_detections`` row for the given molecule ids."""
    if not mol_ids:
        return []
    placeholders = ",".join("?" * len(mol_ids))
    db = DatabaseManager.get(str(library_root))
    rows = db.execute(
        f"SELECT * FROM molecule_detections WHERE mol_id IN ({placeholders})",
        list(mol_ids),
        db="mol",
    )
    return [dict(row) for row in rows]


def apply_corrections(
    library_root: str | Path, updates: Sequence[dict[str, Any]]
) -> None:
    """Apply recorrection updates and correction audit rows in one transaction.

    Each update carries ``mol_id`` / ``properties`` / ``review_status`` and a
    list of ``corrections`` (each with field/old_value/new_value/source/
    created_at).
    """
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as (_kb_conn, mol_conn):
        for item in updates:
            mol_conn.execute(
                "UPDATE molecules "
                "SET properties = ?, review_status = ?, reviewed_at = NULL "
                "WHERE mol_id = ?",
                (item["properties"], item["review_status"], item["mol_id"]),
            )
            for corr in item["corrections"]:
                mol_conn.execute(
                    "INSERT INTO molecule_corrections "
                    "(mol_id, field, old_value, new_value, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        item["mol_id"],
                        corr["field"],
                        corr["old_value"],
                        corr["new_value"],
                        corr["source"],
                        corr["created_at"],
                    ),
                )


# Document-scoped tables cleaned before (re)persisting a document's candidates,
# in deletion order. The shared ``molecules`` table is intentionally absent:
# the same canonical SMILES may be referenced by other documents.
DOC_SCOPED_MOLECULE_TABLES: tuple[str, ...] = (
    "molecule_detections",
    "evidence",
    "markush_fragments",
    "markush_review_candidates",
    "markush_evidence",
    "markush_scaffolds",
    "activities",
)

# Caps for the merged evidence context text (PIPE-05). The total cap preserves
# the historical 500-char storage budget of ``evidence.context_text``; the
# per-item cap keeps one huge excerpt from starving the others.
_CONTEXT_ITEM_CAP = 300
_CONTEXT_TOTAL_CAP = 500
_DOCUMENT_CONTEXT_MARKER = "[context:document]"


def _clean_contexts(texts: Any, *, exclude: set[str] | None = None) -> list[str]:
    """Trim, cap and stably dedupe context strings, preserving order."""
    if not isinstance(texts, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set(exclude) if exclude else set()
    for text in texts:
        if not isinstance(text, str):
            continue
        item = text.strip()[:_CONTEXT_ITEM_CAP]
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _candidate_context_text(candidate: Any) -> str:
    properties = getattr(candidate, "properties", {})
    if not isinstance(properties, dict):
        return ""
    contexts = _clean_contexts(properties.get("role_contexts"))
    if not contexts:
        return ""
    return (_DOCUMENT_CONTEXT_MARKER + "\n" + "\n".join(contexts))[:_CONTEXT_TOTAL_CAP]


def _persist_loop(
    active_conn: Any, db: Any, doc_id: str, candidates: Sequence[Any]
) -> int:
    """Upsert molecules and insert detection/evidence rows on one connection."""
    persisted = 0
    for c in candidates:
        primary = c.detections[0]
        bbox = primary.bbox
        conf_moldet = primary.conf_moldet
        # Page contract boundary: ``primary.page`` is a 0-based ``PageIndex``;
        # evidence rows and the UI use 1-based ``PageNumber``. Convert once.
        primary_page_number = primary.page + 1
        canonical_smiles = c.canonical_smiles
        context_text = _candidate_context_text(c)
        evidence_kind = "figure" if primary.image_path else "text"
        evidence_source = getattr(primary, "source", "image")
        if evidence_source not in {"image", "text", "manual"}:
            evidence_source = "image"
        # Remove stale FTS entries before touching the row so that FTS5
        # external-content DELETE can still see the old values.
        db.delete_molecule_from_mol_search(active_conn, canonical_smiles)
        active_conn.execute(
            """
            INSERT INTO molecules
                (mol_id, smiles, esmiles, name, source_doc, source_type,
                 status, canonical_smiles)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(mol_id) DO UPDATE SET
                canonical_smiles = COALESCE(molecules.canonical_smiles, excluded.canonical_smiles),
                source_doc = COALESCE(NULLIF(molecules.source_doc, ''), excluded.source_doc),
                name = CASE
                    WHEN TRIM(COALESCE(molecules.name, '')) = '' THEN excluded.name
                    ELSE molecules.name
                END
            """,
            (
                canonical_smiles,
                canonical_smiles,
                c.esmiles,
                c.name or "",
                doc_id,
                evidence_source,
                canonical_smiles,
            ),
        )
        db.sync_molecule_to_mol_search(active_conn, canonical_smiles)
        db.sync_molecule_fingerprint(active_conn, canonical_smiles)
        active_conn.execute(
            """
            INSERT INTO molecule_detections (
                mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                crop_relpath, conf_moldet,
                vlm_verified_esmiles
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_smiles,
                doc_id,
                primary.page,
                bbox[0] if bbox else None,
                bbox[1] if bbox else None,
                bbox[2] if bbox else None,
                bbox[3] if bbox else None,
                primary.image_path,
                conf_moldet,
                c.esmiles,
            ),
        )
        active_conn.execute(
            """
            INSERT INTO evidence
                (canonical_smiles, mol_id, evidence_id, doc_id, page,
                 bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 crop_relpath, context_text, role, kind, confidence, source_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'detected', ?, ?, ?)
            """,
            (
                canonical_smiles,
                canonical_smiles,
                getattr(primary, "evidence_id", None),
                doc_id,
                primary_page_number,
                bbox[0] if bbox else None,
                bbox[1] if bbox else None,
                bbox[2] if bbox else None,
                bbox[3] if bbox else None,
                primary.image_path,
                context_text,
                evidence_kind,
                primary.confidence,
                evidence_source,
            ),
        )
        persisted += 1
    return persisted


def persist_candidates(
    library_root: str | Path, doc_id: str, candidates: Sequence[Any]
) -> int:
    """Upsert the given candidates and their detection/evidence rows."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.mol_conn() as active_conn:
        return _persist_loop(active_conn, db, doc_id, candidates)


def replace_document_candidates(
    library_root: str | Path,
    doc_id: str,
    candidates: Sequence[Any],
    activity_updates: Sequence[dict[str, Any]] | None = None,
) -> int:
    """Replace a document's derived rows, then persist and set activity.

    Runs in one transaction: deletes the document's document-scoped rows so a
    retry does not duplicate detections/evidence, persists the candidates, then
    applies ``activity_updates`` (each with mol_id/activity/activity_type/units)
    to their ``molecules`` rows.
    """
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.transaction() as (_kb_conn, active_conn):
        for table in DOC_SCOPED_MOLECULE_TABLES:
            active_conn.execute(f"DELETE FROM {table} WHERE doc_id = ?", (doc_id,))
        persisted = _persist_loop(active_conn, db, doc_id, candidates)
        for update in activity_updates or ():
            active_conn.execute(
                "UPDATE molecules SET activity = ?, activity_type = ?, units = ? "
                "WHERE mol_id = ?",
                (
                    update["activity"],
                    update["activity_type"],
                    update["units"],
                    update["mol_id"],
                ),
            )
    return persisted


__all__ = [
    "apply_corrections",
    "bulk_update_status",
    "clear_detections",
    "create",
    "delete",
    "detection_cache_matches",
    "detection_counts",
    "detections_for_molecules",
    "find_row",
    "get_row",
    "identity_fields",
    "list_corrections",
    "list_page",
    "load_detections",
    "molecules_for_recorrection",
    "persist_candidates",
    "replace_document_candidates",
    "save_detections",
    "search_similarity",
    "search_substructure",
    "search_text",
    "stats",
    "update",
]

"""Domain operations for molecule data.

Read-side helpers for ``molecules`` and ``molecule_images`` (list, search,
evidence chains, location overlap), write-side CRUD used by the molecule
router, plus RDKit-based validation and fingerprinting wrappers used by the
pipeline, the search cache, and the agent tools.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from rdkit import Chem

from ...core.molecule import Molecule, molecule_id
from ...models.molecule import MoleculeListRequest, MoleculeListResponse
from ...pipeline.persist.molecules import filter_persistable_candidates
from ...storage.sqlite.database import DatabaseManager
from ...utils.errors import NotFoundError, ValidationError
from ...utils.ids import short_id
from ...utils.logger import get_logger
from ..documents.pdf_layout import load_document_bboxes

logger = get_logger(__name__)

_JSON_TEXT_COLUMNS = ("labels", "properties")

# Truncation limits for evidence lists returned per molecule.
_EVIDENCE_LIST_LIMIT = 50
_EVIDENCE_FULL_LIMIT = 100_000


def normalize_molecule_row(row: sqlite3.Row | dict) -> dict[str, Any]:
    """Parse database JSON columns and expose frontend field names."""
    item = dict(row)
    for key in _JSON_TEXT_COLUMNS:
        value = item.get(key)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                value = [] if key == "labels" else {}
        elif value is None:
            value = [] if key == "labels" else {}
        item[key] = value
    if "labels" in item:
        item["tags"] = item.pop("labels")
    # Raw fingerprint bytes are not JSON-serializable; drop from API responses.
    item.pop("fingerprint", None)
    return item


def build_crop_url(library_root: str, ev_row: dict[str, Any]) -> str | None:
    """Return the crop image URL for an evidence row, or None if no crop."""
    if not ev_row.get("crop_relpath") or not ev_row.get("doc_id"):
        return None
    rel = Path(ev_row["crop_relpath"]).name
    return f"/api/v1/library/documents/{ev_row['doc_id']}/crop?" + urlencode(
        {"rel_path": rel, "library_root": library_root}
    )


def attach_evidence_batch(
    conn: sqlite3.Connection,
    library_root: str,
    items: list[dict[str, Any]],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Attach ``evidence`` list to each item by canonical_smiles.

    Sort order: kind, doc_id, page, id. Limit per molecule to keep the
    list response bounded. Use the dedicated ``/evidence`` endpoint for
    the full chain.
    """
    if not items:
        return items
    canonicals = sorted(
        {i.get("canonical_smiles") or i.get("mol_id") for i in items if i.get("mol_id")}
    )
    placeholders = ",".join("?" for _ in canonicals)
    rows = conn.execute(
        f"""
        SELECT id, canonical_smiles, doc_id, page,
               bbox_x0, bbox_y0, bbox_x1, bbox_y1, crop_relpath,
               context_text, code_text, role, kind, confidence, source_type,
               created_at
        FROM evidence
        WHERE canonical_smiles IN ({placeholders})
        ORDER BY canonical_smiles, kind, doc_id, page, id
        """,
        canonicals,
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {cs: [] for cs in canonicals}
    for r in rows:
        d = dict(r)
        d["crop_url"] = build_crop_url(library_root, d)
        grouped[d["canonical_smiles"]].append(d)
    for item in items:
        cs = item.get("canonical_smiles") or item.get("mol_id")
        ev = grouped.get(cs, [])
        item["evidence"] = ev[:limit]
        item["evidence_total"] = len(ev)
        if not item.get("source_doc"):
            item["source_doc"] = next(
                (entry["doc_id"] for entry in ev if entry.get("doc_id")), None
            )
    return items


def list_molecules_sync(
    root: str,
    body: MoleculeListRequest,
) -> MoleculeListResponse:
    """Build dynamic filters, counts, and filter options for molecule list."""
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        where_parts = ["1=1"]
        params: list[Any] = []
        if body.status:
            where_parts.append("status = ?")
            params.append(body.status)
        if body.source_type:
            where_parts.append("source_type = ?")
            params.append(body.source_type)
        if body.source_doc:
            where_parts.append(
                "(source_doc = ? OR EXISTS ("
                "SELECT 1 FROM evidence e WHERE e.doc_id = ? AND "
                "(e.mol_id = molecules.mol_id OR "
                "e.canonical_smiles = molecules.canonical_smiles)))"
            )
            params.extend([body.source_doc, body.source_doc])
        if body.activity_presence == "present":
            where_parts.append("activity IS NOT NULL")
        elif body.activity_presence == "missing":
            where_parts.append("activity IS NULL")
        if body.activity_min is not None:
            where_parts.append("activity IS NOT NULL AND activity >= ?")
            params.append(body.activity_min)
        if body.activity_max is not None:
            where_parts.append("activity IS NOT NULL AND activity <= ?")
            params.append(body.activity_max)
        if body.query.strip():
            query = f"%{body.query.strip()}%"
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
        sort_column = sort_columns.get(body.sort_field, "created_at")
        direction = "ASC" if body.sort_direction == "asc" else "DESC"
        nulls_last = "activity IS NULL ASC, " if sort_column == "activity" else ""
        order_by = f"{nulls_last}{sort_column} {direction}, mol_id ASC"

        total = conn.execute(
            f"SELECT COUNT(*) FROM molecules {where}", params
        ).fetchone()[0]

        # Cap matching_ids to keep list responses bounded; with 100k+ molecules
        # the full id list alone costs ~2MB and dominates the response.
        max_matching_ids = 1000
        max_filter_options = 1000
        matching_id_rows = conn.execute(
            f"SELECT mol_id FROM molecules {where} ORDER BY {order_by} LIMIT ?",
            params + [max_matching_ids + 1],
        ).fetchall()
        matching_truncated = len(matching_id_rows) > max_matching_ids
        matching_ids = [r[0] for r in matching_id_rows[:max_matching_ids]]

        offset = (body.page - 1) * body.page_size
        rows = conn.execute(
            f"SELECT * FROM molecules {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            params + [body.page_size, offset],
        ).fetchall()
        items = [normalize_molecule_row(r) for r in rows]
        # Attach evidence chain (truncated for list view).
        items = attach_evidence_batch(conn, root, items, limit=_EVIDENCE_LIST_LIMIT)
        source_types = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT source_type FROM molecules "
                "WHERE source_type IS NOT NULL AND source_type != '' "
                "ORDER BY source_type LIMIT ?",
                (max_filter_options,),
            ).fetchall()
        ]
        source_docs = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT source_doc FROM molecules "
                "WHERE source_doc IS NOT NULL AND source_doc != '' "
                "ORDER BY source_doc LIMIT ?",
                (max_filter_options,),
            ).fetchall()
        ]
        source_docs.extend(
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT doc_id FROM evidence "
                "WHERE doc_id IS NOT NULL AND doc_id != '' "
                "ORDER BY doc_id LIMIT ?",
                (max_filter_options,),
            ).fetchall()
            if row[0] not in source_docs
        )
        source_docs.sort()
    return MoleculeListResponse(
        items=items,
        total=total,
        matching_ids=matching_ids,
        source_types=source_types,
        source_docs=source_docs,
        truncated=matching_truncated,
    )


def _search_molecules_text(
    conn: sqlite3.Connection, query: str, top_k: int
) -> list[dict[str, Any]]:
    # FTS5 parses punctuation such as ``=`` as query syntax. User-entered
    # molecule names and notes must instead be searched as literal text.
    literal_query = f'"{query.replace('"', '""')}"'
    rows = conn.execute(
        "SELECT m.* FROM mol_search ms JOIN molecules m ON ms.rowid = m.rowid "
        "WHERE mol_search MATCH ? LIMIT ?",
        (literal_query, top_k),
    ).fetchall()
    return [normalize_molecule_row(row) for row in rows]


def _search_molecules_substructure(
    conn: sqlite3.Connection, query_smiles: str, top_k: int
) -> list[dict[str, Any]]:
    query_mol = Chem.MolFromSmiles(query_smiles)
    if query_mol is None:
        return []

    rows = conn.execute(
        "SELECT * FROM molecules WHERE fingerprint IS NOT NULL OR smiles IS NOT NULL"
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
            results.append(normalize_molecule_row(row))
            if len(results) >= top_k:
                break
    return results


def _search_molecules_similarity(
    conn: sqlite3.Connection,
    query_smiles: str,
    top_k: int,
    threshold: float,
) -> list[dict[str, Any]]:
    query_mol = Molecule(mol_id="", canonical_smiles=query_smiles)
    if query_mol.fingerprint is None:
        return []

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
            item = normalize_molecule_row(row)
            item["similarity"] = similarity
            scored.append((similarity, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def search_molecules(
    library_root: str | None,
    query: str,
    top_k: int = 10,
    mode: str = "auto",
    similarity_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Search molecules using text, substructure, or similarity mode.

    Args:
        library_root: Project root directory.
        query: Search query; treated as SMILES in structure modes or as text.
        top_k: Maximum number of results.
        mode: One of ``auto``, ``text``, ``substructure``, ``similarity``.
            In ``auto`` mode, valid SMILES strings use substructure search;
            everything else uses FTS5 text search.
        similarity_threshold: Minimum Tanimoto similarity for similarity mode.
    """
    with DatabaseManager.get(library_root).mol_conn() as conn:
        if mode == "text":
            return _search_molecules_text(conn, query, top_k)
        if mode == "substructure":
            return _search_molecules_substructure(conn, query, top_k)
        if mode == "similarity":
            return _search_molecules_similarity(
                conn, query, top_k, similarity_threshold
            )
        # auto
        query_mol = Molecule(mol_id="", canonical_smiles=query)
        if query_mol.is_valid():
            return _search_molecules_substructure(conn, query, top_k)
        return _search_molecules_text(conn, query, top_k)


def substructure_search_db(
    library_root: str, query: str, top_k: int
) -> list[dict[str, Any]]:
    """Substructure search against the library database (blocking)."""
    with DatabaseManager.get(library_root).mol_conn() as conn:
        return _search_molecules_substructure(conn, query, top_k)


def similarity_search_db(
    library_root: str, query: str, top_k: int, threshold: float
) -> list[dict[str, Any]]:
    """Similarity search against the library database (blocking)."""
    with DatabaseManager.get(library_root).mol_conn() as conn:
        return _search_molecules_similarity(conn, query, top_k, threshold)


def _bbox_contains(
    query: tuple[float, float, float, float],
    stored: tuple[float, float, float, float],
) -> bool:
    """Return whether the stored box contains the query box."""
    qx0, qy0, qx1, qy1 = query
    sx0, sy0, sx1, sy1 = stored
    return sx0 <= qx0 and sx1 >= qx1 and sy0 <= qy0 and sy1 >= qy1


def molecules_by_location(
    root: str,
    doc_id: str,
    page: int,
    bbox: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Find molecule evidence overlapping a document location.

    The public page is 1-based. Primary source is the consolidated per-document
    SQL-backed source evidence plus candidate associations read via
    :func:`mbforge.services.documents.pdf_layout.load_document_bboxes`; those
    candidate detections are unioned with the interactive detection-cache table
    (``molecule_detections``), so molecules surface both after persist and
    after an interactive page recognition. The persist-time mirrors of primary
    detections in that table are deduped against the index matches. Without a
    validated v2 branch, only interactive detection-cache rows are available;
    legacy ``evidence`` rows are not used as a source-evidence fallback.

    *bbox* keeps the historical ``(x0, x1, y0, y1)`` tuple order used by the
    router; the values themselves are PDF points.
    """
    x0, x1, y0, y1 = bbox
    query_box = (x0, y0, x1, y1)
    extracted, candidates = load_document_bboxes(root, doc_id)
    if extracted is None and candidates is None:
        candidates = []

    matches: list[dict[str, Any]] = []
    if candidates is not None:
        persistable = filter_persistable_candidates(doc_id, candidates, warn=False)
        matches.extend(_index_matches(doc_id, page, query_box, persistable))
    matches.extend(_cache_matches(root, doc_id, page, query_box))
    matches = _dedupe_matches(matches)
    _refresh_identity_fields(root, matches)
    for item in matches:
        item["crop_url"] = build_crop_url(root, item)
        item.pop("crop_relpath", None)
    matches.sort(key=lambda m: (m["page"], m["mol_id"] or "", m["canonical_smiles"]))
    return matches


def _index_matches(
    doc_id: str,
    page: int,
    query_box: tuple[float, float, float, float],
    persistable: list[Molecule],
) -> list[dict[str, Any]]:
    """Primary-detection matches from the bbox index candidates.

    Page basis: ``DetectionSource.page`` is a 0-based ``PageIndex`` while the
    public page is a 1-based ``PageNumber`` — the same single conversion the
    persist path performs. Identity follows persist: ``mol_id`` is the
    canonical SMILES.
    """
    matches: list[dict[str, Any]] = []
    for candidate in persistable:
        primary = candidate.detections[0]
        canonical = candidate.canonical_smiles
        if primary.page != page - 1 or primary.bbox is None:
            continue
        if not _bbox_contains(query_box, primary.bbox):
            continue
        matches.append(
            {
                "mol_id": canonical,
                "canonical_smiles": canonical,
                "doc_id": doc_id,
                "name": "",
                "confidence": primary.confidence,
                "page": page,
                "bbox": {
                    "x0": primary.bbox[0],
                    "y0": primary.bbox[1],
                    "x1": primary.bbox[2],
                    "y1": primary.bbox[3],
                },
                "crop_relpath": primary.image_path,
            }
        )
    return matches


def _cache_matches(
    root: str,
    doc_id: str,
    page: int,
    query_box: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Interactive detection-cache rows (``molecule_detections``).

    The table mixes persist-time mirrors (deduped against index matches by
    :func:`_dedupe_matches`) with interactive page-recognition rows written
    before persist. Its ``page`` stays 0-based, so the boundary converts once.
    """
    qx0, qy0, qx1, qy1 = query_box
    db = DatabaseManager.get(root)
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
        confidence: float | None = row["conf_moldet"]
        matches.append(
            {
                "mol_id": row["mol_id"],
                "canonical_smiles": row["mol_id"]
                or (row["vlm_verified_esmiles"] or ""),
                "doc_id": doc_id,
                "name": "",
                "confidence": confidence,
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


def _dedupe_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union-style dedupe by identity, page and bbox.

    Persist writes each primary detection into ``molecule_detections`` as a
    mirror; that mirror must not surface as a second match. Name/canonical
    fields are excluded from the key — they are derived and refreshed
    afterwards.
    """
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for item in matches:
        box = item["bbox"]
        key = (
            item["mol_id"],
            item["page"],
            box["x0"],
            box["y0"],
            box["x1"],
            box["y1"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _refresh_identity_fields(root: str, matches: list[dict[str, Any]]) -> None:
    """Prefer current ``molecules`` fields for matched ids (SQL-path parity).

    The SQL path joined ``molecules`` live; the index snapshot may lag behind
    renames or SMILES corrections. Rows without a molecules record (e.g.
    candidates before persist) keep their index identity, and an empty name
    falls back to ``mol_id`` like ``COALESCE(NULLIF(m.name, ''), …)``.
    """
    ids = sorted({m["mol_id"] for m in matches if m["mol_id"]})
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        rows = conn.execute(
            f"SELECT mol_id, canonical_smiles, name FROM molecules "
            f"WHERE mol_id IN ({placeholders})",
            ids,
        ).fetchall()
    by_id = {row["mol_id"]: row for row in rows}
    for item in matches:
        row = by_id.get(item["mol_id"]) if item["mol_id"] else None
        if row is not None:
            if row["canonical_smiles"]:
                item["canonical_smiles"] = row["canonical_smiles"]
            db_name = (row["name"] or "").strip()
            if db_name:
                item["name"] = db_name
        if not item["name"]:
            item["name"] = item["mol_id"] or ""


def get_molecule(root: str, mol_id: str) -> dict[str, Any]:
    """Return a molecule row by ``mol_id`` or raise NotFoundError."""
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT * FROM molecules WHERE mol_id = ?", (mol_id,)
        ).fetchone()
    if not row:
        raise NotFoundError("molecule not found", detail=f"mol_id={mol_id}")
    return normalize_molecule_row(row)


def molecule_evidence_chain(
    root: str, canonical_smiles: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the full evidence chain for a canonical molecule.

    Joins ``molecules`` for metadata; returns the molecule record plus
    the full ``evidence`` list (untruncated).
    """
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        mol_row = conn.execute(
            "SELECT * FROM molecules WHERE mol_id = ? OR canonical_smiles = ?",
            (canonical_smiles, canonical_smiles),
        ).fetchone()
        if not mol_row:
            raise NotFoundError(
                "molecule not found", detail=f"canonical_smiles={canonical_smiles}"
            )
        items = attach_evidence_batch(
            conn, root, [normalize_molecule_row(mol_row)], limit=_EVIDENCE_FULL_LIMIT
        )
        mol = items[0]
    return mol, mol.get("evidence", [])


def create_molecule(
    root: str,
    mol_id: str | None,
    smiles: str,
    esmiles: str | None,
    name: str | None,
    source_type: str | None,
) -> str:
    """Insert or replace a molecule and refresh its search index."""
    db = DatabaseManager.get(root)
    if not mol_id:
        # Deterministic structural id (canonical SMILES) so identical
        # molecules dedup; random fallback when nothing parseable to key on.
        mol_id = molecule_id(smiles) or short_id()
    with db.mol_conn() as conn:
        DatabaseManager.delete_molecule_from_mol_search(conn, mol_id)
        conn.execute(
            "INSERT OR REPLACE INTO molecules (mol_id, smiles, esmiles, name, source_type, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mol_id, smiles, esmiles, name, source_type, "active"),
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, mol_id)
        DatabaseManager.sync_molecule_fingerprint(conn, mol_id)
    return mol_id


def bulk_update_status(root: str, mol_ids: list[str], status: str) -> tuple[int, int]:
    """Set ``status`` for the given molecules. Returns (updated, skipped)."""
    db = DatabaseManager.get(root)
    unique_ids = list(dict.fromkeys(mol_ids))
    placeholders = ",".join("?" for _ in unique_ids)
    with db.mol_conn() as conn:
        cursor = conn.execute(
            f"UPDATE molecules SET status = ? WHERE mol_id IN ({placeholders})",
            [status, *unique_ids],
        )
        updated = cursor.rowcount
    return updated, len(unique_ids) - updated


def update_molecule(root: str, mol_id: str, updates: dict[str, Any]) -> None:
    """Apply column updates and record a SMILES correction when it changes.

    *updates* keys must be DB column names; list/dict values are stored as
    JSON text. Search-index and fingerprint tables are refreshed.
    """
    if not updates:
        raise ValidationError("no fields to update")
    db = DatabaseManager.get(root)
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
        DatabaseManager.delete_molecule_from_mol_search(conn, mol_id)
        conn.execute(
            f"UPDATE molecules SET {', '.join(f'{k} = ?' for k in updates)} WHERE mol_id = ?",
            params,
        )
        DatabaseManager.sync_molecule_to_mol_search(conn, mol_id)


def list_molecule_corrections(root: str, mol_id: str) -> list[dict[str, Any]]:
    """Return append-only manual corrections for a molecule."""
    db = DatabaseManager.get(root)
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


def delete_molecules(root: str, mol_ids: list[str]) -> int:
    """Delete molecules and their search-index rows. Returns rows deleted."""
    db = DatabaseManager.get(root)
    with db.mol_conn() as conn:
        return DatabaseManager.delete_molecule_records(conn, mol_ids)


def molecule_stats(root: str) -> dict[str, Any]:
    """Return total plus per-status and per-source counts."""
    db = DatabaseManager.get(root)
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

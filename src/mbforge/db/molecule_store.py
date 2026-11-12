"""SQLite data access for the molecule catalog.

Owns every query the molecule use cases need (list, get, create, update,
delete, stats, search, corrections, identity, evidence) so the service layer
never executes SQL.  Functions return raw row dicts; the service layer
normalizes and shapes them.

Detection-cache I/O lives in ``detection_store``; candidate publication lives
in ``molecule_candidates``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rdkit import Chem

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.db.sqlite.rows import row_to_dict
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
    with db.connection() as conn:
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
                "SELECT 1 FROM molecule_detections md WHERE md.doc_id = ? AND "
                "md.mol_id = molecules.mol_id))"
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
                "SELECT DISTINCT doc_id FROM molecule_detections "
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
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM molecules WHERE mol_id = ?", (mol_id,)
        ).fetchone()
    return row_to_dict(row)


def find_row(library_root: str | Path, canonical_smiles: str) -> dict[str, Any] | None:
    """Return one ``molecules`` row by ``mol_id`` or ``canonical_smiles``."""
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM molecules WHERE mol_id = ? OR canonical_smiles = ?",
            (canonical_smiles, canonical_smiles),
        ).fetchone()
    return row_to_dict(row)


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
    with db.connection() as conn:
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
    with db.connection() as conn:
        cursor = conn.execute(
            f"UPDATE molecules SET status = ? WHERE mol_id IN ({placeholders})",
            [status, *unique_ids],
        )
        return int(cursor.rowcount)


def update(
    library_root: str | Path,
    mol_id: str,
    updates: dict[str, Any],
    *,
    correction_source: str = "molecule_update",
) -> None:
    """Apply column updates and record a SMILES correction when it changes.

    *updates* keys must be DB column names; list/dict values are stored as JSON
    text. Search-index and fingerprint tables are refreshed.

    A changed ``smiles`` also refreshes ``canonical_smiles``: it is the key the rest
    of the app finds this molecule by, so leaving it on the old structure kept the
    row answering with a SMILES nobody had just written.
    """
    db = DatabaseManager.get(str(library_root))
    new_smiles = updates.get("smiles")
    if isinstance(new_smiles, str) and new_smiles.strip():
        canonical = _canonical_smiles(new_smiles)
        if canonical:
            updates = {**updates, "canonical_smiles": canonical}
    params: list[Any] = []
    for val in updates.values():
        if isinstance(val, (list, dict)):
            val = json.dumps(val)
        params.append(val)
    params.append(mol_id)
    with db.connection() as conn:
        previous = conn.execute(
            "SELECT smiles FROM molecules WHERE mol_id = ?", (mol_id,)
        ).fetchone()
        if new_smiles is not None and previous and previous[0] != new_smiles:
            conn.execute(
                """
                INSERT INTO molecule_corrections
                    (mol_id, field, old_value, new_value, source)
                VALUES (?, 'smiles', ?, ?, ?)
                """,
                (mol_id, previous[0], new_smiles, correction_source),
            )
        db.delete_molecule_from_mol_search(conn, mol_id)
        conn.execute(
            f"UPDATE molecules SET {', '.join(f'{k} = ?' for k in updates)} "
            "WHERE mol_id = ?",
            params,
        )
        db.sync_molecule_to_mol_search(conn, mol_id)


def _canonical_smiles(smiles: str) -> str:
    """RDKit canonical form of ``smiles``, or "" when it does not parse.

    A structure that cannot be parsed is left exactly as the reviewer typed it:
    storing a guessed canonical form would silently break identity matching.
    """
    try:
        from rdkit import Chem

        molecule = Chem.MolFromSmiles(smiles)
        return Chem.MolToSmiles(molecule) if molecule is not None else ""
    except Exception as exc:  # noqa: BLE001 - RDKit absence must not break an edit
        logger.debug("canonical SMILES unavailable: %s", exc)
        return ""


def list_corrections(library_root: str | Path, mol_id: str) -> list[dict[str, Any]]:
    """Return append-only manual corrections for a molecule."""
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
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
    with db.connection() as conn:
        return DatabaseManager.delete_molecule_records(conn, mol_ids)


def stats(library_root: str | Path) -> dict[str, Any]:
    """Return total plus per-status and per-source counts."""
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
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
    library_root: str | Path, query: str, top_k: int, *, doc_id: str = ""
) -> list[dict[str, Any]]:
    """FTS5 text search over molecule names/notes (literal, not query syntax)."""
    # FTS5 parses punctuation such as ``=`` as query syntax. User-entered
    # molecule names and notes must instead be searched as literal text.
    literal_query = f'"{query.replace('"', '""')}"'
    db = DatabaseManager.get(str(library_root))
    scope = "AND m.source_doc = ? " if doc_id else ""
    params: list[Any] = [literal_query]
    if doc_id:
        params.append(doc_id)
    params.append(top_k)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT m.* FROM mol_search ms JOIN molecules m ON ms.rowid = m.rowid "
            f"WHERE mol_search MATCH ? {scope}LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def search_substructure(
    library_root: str | Path, query_smiles: str, top_k: int, *, doc_id: str = ""
) -> list[dict[str, Any]]:
    """Substructure search against the library database (blocking)."""
    query_mol = Chem.MolFromSmiles(query_smiles)
    if query_mol is None:
        return []
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM molecules "
            "WHERE fingerprint IS NOT NULL OR smiles IS NOT NULL"
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        if doc_id and row["source_doc"] != doc_id:
            continue
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
    library_root: str | Path,
    query_smiles: str,
    top_k: int,
    threshold: float,
    *,
    doc_id: str = "",
) -> list[dict[str, Any]]:
    """Similarity search against the library database (blocking)."""
    query_mol = Molecule(mol_id="", canonical_smiles=query_smiles)
    if query_mol.fingerprint is None:
        return []
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM molecules WHERE fingerprint IS NOT NULL"
        ).fetchall()
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        if doc_id and row["source_doc"] != doc_id:
            continue
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
    with db.connection() as conn:
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


def designated_structures(
    library_root: str | Path, doc_id: str
) -> list[dict[str, Any]]:
    """Return this document's concrete structures with their designation (if any).

    ``name`` is the number printed beside the drawing; an empty one means the
    crop-label OCR missed it, which is ordinary on a dense page. Those rows are
    returned too: missing labels do not discard recognised structures, but mass
    agreement alone cannot establish their designation.

    Callers must exclude Markush scaffolds before joining designations: a scheme
    label such as ``I-A`` does not identify a concrete finished compound.
    """
    if not doc_id:
        return []
    db = DatabaseManager.get(str(library_root))
    rows = db.execute(
        "SELECT name, canonical_smiles FROM molecules "
        "WHERE source_doc = ? AND TRIM(COALESCE(canonical_smiles, '')) != ''",
        (doc_id,),
    )
    return [
        {
            "name": str(row["name"] or "").strip(),
            "canonical_smiles": row["canonical_smiles"],
        }
        for row in rows
    ]


def identity_fields(
    library_root: str | Path, mol_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Return ``{mol_id: {canonical_smiles, name}}`` for the given ids."""
    ids = sorted({mol_id for mol_id in mol_ids if mol_id})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
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
    rows = db.execute(query, params)
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
    )
    return [dict(row) for row in rows]


def document_detection_count(library_root: str | Path, doc_id: str) -> int:
    """Return how many structure detections this document produced.

    Used to tell "the source never drew this compound" apart from "a structure
    was detected but could not be bound": without the count the two gaps look
    identical, and only one of them is worth fixing.
    """
    if not doc_id:
        return 0
    db = DatabaseManager.get(str(library_root))
    rows = db.execute(
        "SELECT COUNT(*) AS c FROM molecule_detections WHERE doc_id = ?",
        (doc_id,),
    )
    return int(rows[0]["c"]) if rows else 0


def document_label_numbers(library_root: str | Path, doc_id: str) -> set[str]:
    """Return the compound designations the document's detected structures carry.

    The full printed designation is returned (``77``, ``77-A``), not its numeric
    prefix: ``77-A`` is a different compound from ``77``, so treating them as the
    same number would claim the document drew a structure it never drew.
    """
    if not doc_id:
        return set()
    db = DatabaseManager.get(str(library_root))
    rows = db.execute(
        "SELECT m.name, m.labels FROM molecules m "
        "JOIN molecule_detections md ON md.mol_id = m.mol_id "
        "WHERE md.doc_id = ? GROUP BY m.mol_id",
        (doc_id,),
    )
    numbers: set[str] = set()
    for row in rows:
        name = row["name"] if isinstance(row["name"], str) else ""
        if name.strip():
            numbers.add(name.strip())
        raw_labels = row["labels"]
        if isinstance(raw_labels, str) and raw_labels.strip():
            try:
                labels = json.loads(raw_labels)
            except json.JSONDecodeError:
                labels = []
            for label in labels if isinstance(labels, list) else []:
                if isinstance(label, str) and label.strip():
                    numbers.add(label.strip())
    return numbers


def apply_corrections(
    library_root: str | Path, updates: Sequence[dict[str, Any]]
) -> None:
    """Apply recorrection updates and correction audit rows in one transaction.

    Each update carries ``mol_id`` / ``properties`` / ``review_status`` and a
    list of ``corrections`` (each with field/old_value/new_value/source/
    created_at).
    """
    db = DatabaseManager.get(str(library_root))
    with db.transaction() as conn:
        for item in updates:
            conn.execute(
                "UPDATE molecules "
                "SET properties = ?, review_status = ?, reviewed_at = NULL "
                "WHERE mol_id = ?",
                (item["properties"], item["review_status"], item["mol_id"]),
            )
            for corr in item["corrections"]:
                conn.execute(
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


# Projection of a molecule_detections row into the flat molecule-evidence
# contract. ``kind``/``source_type`` are derived from crop presence (preserving
# the retired ``evidence`` table's semantics); ``page`` is converted to the
# 1-based PageNumber the API/UI use.
_EVIDENCE_COLUMNS = """
    md.id AS id,
    md.mol_id AS mol_id,
    md.evidence_id AS evidence_id,
    COALESCE(m.canonical_smiles, md.mol_id) AS canonical_smiles,
    md.doc_id AS doc_id,
    md.page + 1 AS page,
    md.bbox_x0 AS bbox_x0, md.bbox_y0 AS bbox_y0,
    md.bbox_x1 AS bbox_x1, md.bbox_y1 AS bbox_y1,
    md.crop_relpath AS crop_relpath,
    md.context_text AS context_text,
    NULL AS code_text,
    'detected' AS role,
    CASE WHEN COALESCE(md.crop_relpath, '') != '' THEN 'figure' ELSE 'text' END AS kind,
    md.conf_moldet AS confidence,
    CASE WHEN COALESCE(md.crop_relpath, '') != '' THEN 'image' ELSE 'text' END AS source_type,
    NULL AS created_at
"""


def list_molecule_evidence(
    library_root: str | Path, canonical_smiles: Sequence[str]
) -> list[dict[str, Any]]:
    """Return the molecule evidence chain for the given canonical SMILES.

    The chain is derived from ``molecule_detections`` (the molecule-keyed
    location table): each row carries page (1-based), bbox, crop, context and
    the ``evidence_id`` that links to its canonical ``source_evidence`` row.
    """
    canonicals = [c for c in canonical_smiles if c]
    if not canonicals:
        return []
    placeholders = ",".join("?" for _ in canonicals)
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT {_EVIDENCE_COLUMNS} "
            "FROM molecule_detections md "
            "LEFT JOIN molecules m ON m.mol_id = md.mol_id "
            f"WHERE m.canonical_smiles IN ({placeholders}) "
            f"OR md.mol_id IN ({placeholders}) "
            "ORDER BY kind, md.doc_id, md.page, md.id",
            canonicals + canonicals,
        ).fetchall()
    return [dict(row) for row in rows]


def evidence_for_molecules(
    library_root: str | Path,
    mol_ids: Sequence[str],
    canonicals: Sequence[str],
) -> list[dict[str, Any]]:
    """Return chain rows matching any ``mol_id`` or canonical SMILES."""
    mol_ids = [m for m in mol_ids if m]
    canonicals = [c for c in canonicals if c]
    clauses: list[str] = []
    params: list[Any] = []
    if mol_ids:
        clauses.append(f"md.mol_id IN ({','.join('?' * len(mol_ids))})")
        params.extend(mol_ids)
    if canonicals:
        clauses.append(f"m.canonical_smiles IN ({','.join('?' * len(canonicals))})")
        params.extend(canonicals)
    if not clauses:
        return []
    db = DatabaseManager.get(str(library_root))
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT {_EVIDENCE_COLUMNS} FROM molecule_detections md "
            "LEFT JOIN molecules m ON m.mol_id = md.mol_id "
            f"WHERE {' OR '.join(clauses)}",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


__all__ = [
    "apply_corrections",
    "bulk_update_status",
    "create",
    "delete",
    "detection_cache_matches",
    "detections_for_molecules",
    "evidence_for_molecules",
    "find_row",
    "get_row",
    "identity_fields",
    "list_corrections",
    "list_molecule_evidence",
    "list_page",
    "molecules_for_recorrection",
    "search_similarity",
    "search_substructure",
    "search_text",
    "stats",
    "update",
]

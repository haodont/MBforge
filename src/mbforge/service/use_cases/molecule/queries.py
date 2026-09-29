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

from mbforge.domain.molecule import Molecule, molecule_id
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger
from mbforge.service.dto.molecule import MoleculeListRequest, MoleculeListResponse
from mbforge.service.pipeline.persist.molecules import filter_persistable_candidates
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.pdf_layout import load_document_bboxes

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


def _shape_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    """Reshape a flat ``evidence`` row into the API evidence contract.

    ``bbox`` is nested (``x0..y1``) so the frontend can deep-link straight to
    ``page`` + ``bbox``; ``evidence_id`` links the row to its canonical
    ``source_evidence`` entry so a molecule entry and its page box share one id
    space for cross-highlighting.
    """
    return {
        "id": row.get("id"),
        "evidence_id": row.get("evidence_id"),
        "canonical_smiles": row.get("canonical_smiles"),
        "doc_id": row.get("doc_id"),
        "page": row.get("page"),
        "bbox": {
            "x0": row.get("bbox_x0"),
            "y0": row.get("bbox_y0"),
            "x1": row.get("bbox_x1"),
            "y1": row.get("bbox_y1"),
        },
        "crop_relpath": row.get("crop_relpath"),
        "context_text": row.get("context_text"),
        "code_text": row.get("code_text"),
        "role": row.get("role"),
        "kind": row.get("kind"),
        "confidence": row.get("confidence"),
        "source_type": row.get("source_type"),
        "created_at": row.get("created_at"),
    }


def attach_evidence_batch(
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
    rows = get_repositories(library_root).molecules.list_molecule_evidence(canonicals)
    grouped: dict[str, list[dict[str, Any]]] = {cs: [] for cs in canonicals}
    for r in rows:
        d = _shape_evidence_row(r)
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
    page = get_repositories(root).molecules.list_page(body)
    items = [normalize_molecule_row(r) for r in page["rows"]]
    # Attach evidence chain (truncated for list view).
    items = attach_evidence_batch(root, items, limit=_EVIDENCE_LIST_LIMIT)
    return MoleculeListResponse(
        items=items,
        total=page["total"],
        matching_ids=page["matching_ids"],
        source_types=page["source_types"],
        source_docs=page["source_docs"],
        truncated=page["truncated"],
    )


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
    if library_root is None:
        return []
    molecules = get_repositories(library_root).molecules
    if mode == "text":
        rows = molecules.search_text(query, top_k)
    elif mode == "substructure":
        rows = molecules.search_substructure(query, top_k)
    elif mode == "similarity":
        rows = molecules.search_similarity(query, top_k, similarity_threshold)
    else:
        # auto: valid SMILES uses substructure search, otherwise text search.
        query_mol = Molecule(mol_id="", canonical_smiles=query)
        if query_mol.is_valid():
            rows = molecules.search_substructure(query, top_k)
        else:
            rows = molecules.search_text(query, top_k)
    return [normalize_molecule_row(row) for row in rows]


def substructure_search_db(
    library_root: str, query: str, top_k: int
) -> list[dict[str, Any]]:
    """Substructure search against the library database (blocking)."""
    rows = get_repositories(library_root).molecules.search_substructure(query, top_k)
    return [normalize_molecule_row(row) for row in rows]


def similarity_search_db(
    library_root: str, query: str, top_k: int, threshold: float
) -> list[dict[str, Any]]:
    """Similarity search against the library database (blocking)."""
    rows = get_repositories(library_root).molecules.search_similarity(
        query, top_k, threshold
    )
    return [normalize_molecule_row(row) for row in rows]


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
    :func:`mbforge.service.use_cases.documents.pdf_layout.load_document_bboxes`; those
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
    return get_repositories(root).molecules.detection_cache_matches(
        doc_id, page, query_box
    )


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
    by_id = get_repositories(root).molecules.identity_fields(ids)
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
    row = get_repositories(root).molecules.get_row(mol_id)
    if row is None:
        raise NotFoundError("molecule not found", detail=f"mol_id={mol_id}")
    return normalize_molecule_row(row)


def molecule_evidence_chain(
    root: str, canonical_smiles: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the full evidence chain for a canonical molecule.

    Joins ``molecules`` for metadata; returns the molecule record plus
    the full ``evidence`` list (untruncated).
    """
    mol_row = get_repositories(root).molecules.find_row(canonical_smiles)
    if mol_row is None:
        raise NotFoundError(
            "molecule not found", detail=f"canonical_smiles={canonical_smiles}"
        )
    items = attach_evidence_batch(
        root, [normalize_molecule_row(mol_row)], limit=_EVIDENCE_FULL_LIMIT
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
    if not mol_id:
        # Deterministic structural id (canonical SMILES) so identical
        # molecules dedup; random fallback when nothing parseable to key on.
        mol_id = molecule_id(smiles) or short_id()
    get_repositories(root).molecules.create(mol_id, smiles, esmiles, name, source_type)
    return mol_id


def bulk_update_status(root: str, mol_ids: list[str], status: str) -> tuple[int, int]:
    """Set ``status`` for the given molecules. Returns (updated, skipped)."""
    unique_ids = list(dict.fromkeys(mol_ids))
    updated = get_repositories(root).molecules.bulk_update_status(unique_ids, status)
    return updated, len(unique_ids) - updated


def update_molecule(root: str, mol_id: str, updates: dict[str, Any]) -> None:
    """Apply column updates and record a SMILES correction when it changes.

    *updates* keys must be DB column names; list/dict values are stored as
    JSON text. Search-index and fingerprint tables are refreshed.
    """
    if not updates:
        raise ValidationError("no fields to update")
    get_repositories(root).molecules.update(mol_id, updates)


def list_molecule_corrections(root: str, mol_id: str) -> list[dict[str, Any]]:
    """Return append-only manual corrections for a molecule."""
    return get_repositories(root).molecules.list_corrections(mol_id)


def delete_molecules(root: str, mol_ids: list[str]) -> int:
    """Delete molecules and their search-index rows. Returns rows deleted."""
    return get_repositories(root).molecules.delete(mol_ids)


def molecule_stats(root: str) -> dict[str, Any]:
    """Return total plus per-status and per-source counts."""
    return get_repositories(root).molecules.stats()

"""Candidate publication into ``molecules`` / ``molecule_detections``.

Extract and Patent stages hand parsed candidates to these functions, which
upsert the molecules table plus the per-detection rows and optional activity
updates.  Query/CRUD access lives in ``molecule_store``; the detection cache
lookup/save API lives in ``detection_store``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager

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


def _candidate_labels(candidate: Any) -> str:
    """Return the JSON list of designations the molecule's drawings carry.

    One structure is drawn more than once in a patent — as a compound in the
    list and as an intermediate in the scheme — and the designations of those
    drawings differ. The ``labels`` column keeps all of them, so a read that
    asks "does this document draw compound X?" sees every name the molecule
    answers to, not only the first one written.
    """
    properties = getattr(candidate, "properties", {})
    names: list[str] = []
    if isinstance(properties, dict):
        for key in ("detection_names", "name_candidates"):
            value = properties.get(key)
            if isinstance(value, list):
                for item in value:
                    name = item.get("name") if isinstance(item, dict) else item
                    if isinstance(name, str) and name.strip() and name not in names:
                        names.append(name)
    return json.dumps(names, ensure_ascii=False)


def _candidate_properties(candidate: Any) -> str:
    """Serialize the candidate's own annotations for the molecule row.

    The role classification and an agent promotion are decisions about this
    structure; without them the row cannot say why a drawing the prose around
    it looked generic still entered the concrete library.
    """
    properties = getattr(candidate, "properties", {})
    if not isinstance(properties, dict):
        return "{}"
    return json.dumps(properties, ensure_ascii=False, default=str)


def _persist_loop(
    active_conn: Any, db: Any, doc_id: str, candidates: Sequence[Any]
) -> int:
    """Upsert molecules and detection rows on one connection."""
    persisted = 0
    for c in candidates:
        primary = c.detections[0]
        bbox = primary.bbox
        conf_moldet = primary.conf_moldet
        canonical_smiles = c.canonical_smiles
        context_text = _candidate_context_text(c)
        evidence_source = getattr(primary, "source", "image")
        if evidence_source not in {"image", "text", "manual"}:
            evidence_source = "image"
        # Remove stale FTS entries before touching the row so that FTS5
        # external-content DELETE can still see the old values.
        db.delete_molecule_from_mol_search(active_conn, canonical_smiles)
        active_conn.execute(
            """
            INSERT INTO molecules
                (mol_id, smiles, esmiles, name, labels, source_doc, source_type,
                 status, canonical_smiles, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(mol_id) DO UPDATE SET
                canonical_smiles = COALESCE(molecules.canonical_smiles, excluded.canonical_smiles),
                source_doc = COALESCE(NULLIF(molecules.source_doc, ''), excluded.source_doc),
                name = CASE
                    WHEN TRIM(COALESCE(molecules.name, '')) = '' THEN excluded.name
                    ELSE molecules.name
                END,
                labels = excluded.labels,
                properties = CASE
                    WHEN COALESCE(molecules.properties, '') IN ('', '{}')
                        THEN excluded.properties
                    ELSE molecules.properties
                END
            """,
            (
                canonical_smiles,
                canonical_smiles,
                c.esmiles,
                c.name or "",
                _candidate_labels(c),
                doc_id,
                evidence_source,
                canonical_smiles,
                _candidate_properties(c),
            ),
        )
        db.sync_molecule_to_mol_search(active_conn, canonical_smiles)
        db.sync_molecule_fingerprint(active_conn, canonical_smiles)
        # ``molecule_detections`` is UNIQUE(mol_id, doc_id, page): a patent often
        # draws the same structure more than once on a page (a scheme and its
        # table row), and a plain INSERT raises on the second one — which used to
        # abort the whole document's persist and leave almost every molecule
        # without a detection row. The first occurrence keeps its evidence link;
        # a later duplicate is the same fact for this purpose.
        if primary.page is None:
            # ``page`` is NOT NULL; a detection without one must never be
            # defaulted to page 1.
            persisted += 1
            continue
        active_conn.execute(
            """
            INSERT INTO molecule_detections (
                mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                crop_relpath, conf_moldet,
                vlm_verified_esmiles, evidence_id, context_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mol_id, doc_id, page) DO UPDATE SET
                evidence_id = COALESCE(molecule_detections.evidence_id, excluded.evidence_id),
                context_text = CASE
                    WHEN TRIM(COALESCE(molecule_detections.context_text, '')) = ''
                        THEN excluded.context_text
                    ELSE molecule_detections.context_text
                END
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
                getattr(primary, "evidence_id", None),
                context_text,
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
    with db.connection() as active_conn:
        return _persist_loop(active_conn, db, doc_id, candidates)


def persist_candidates_in_transaction(
    conn: Any,
    db: Any,
    doc_id: str,
    candidates: Sequence[Any],
    activity_updates: Sequence[dict[str, Any]] | None = None,
) -> int:
    """Persist the document's candidates on *conn*; the caller owns the transaction.

    Structure ownership belongs to Extract, which stores every concrete structure
    it recognizes. The Patent stage passes only the handful it could prove a
    reading belongs to, so it must not clear the document's detections: doing so
    deleted everything this pass did not mention (a 113-page patent went from 290
    stored molecules to 8, all of them stripped of their detection rows), and a
    document whose facts came out empty lost its structures entirely.

    Only the ``molecule_detections`` of **these** candidates are replaced, so
    re-publishing the same facts stays idempotent while every other structure
    keeps its row. Clearing a document's structures when its facts are empty is
    not this stage's job — that belongs to re-extraction, which is what replaced
    the evidence.
    """
    if not candidates:
        return 0
    mol_ids = sorted(
        {
            str(getattr(candidate, "canonical_smiles", "") or "")
            for candidate in candidates
        }
        - {""}
    )
    for start in range(0, len(mol_ids), 500):
        chunk = mol_ids[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(
            "DELETE FROM molecule_detections "
            f"WHERE doc_id = ? AND mol_id IN ({placeholders})",
            [doc_id, *chunk],
        )
    persisted = _persist_loop(conn, db, doc_id, candidates)
    for update in activity_updates or ():
        conn.execute(
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
    with db.transaction() as active_conn:
        return persist_candidates_in_transaction(
            active_conn, db, doc_id, candidates, activity_updates
        )


__all__ = [
    "persist_candidates",
    "persist_candidates_in_transaction",
    "replace_document_candidates",
]

"""Persist scaffold and fragment candidates into the Markush tables.

Writes classified Markush structures to ``markush_scaffolds`` and
``markush_fragments`` with detection metadata and coreference labels
preserved for the review UI and downstream enumeration.

Uses the :class:`MarkushScaffold` / :class:`MarkushFragment` entity
classes as the canonical in-memory shape so the SQL field list is
derived from ``entity.to_dict()`` rather than hand-coded tuples.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from mbforge.core.molecule import MarkushFragment, MarkushScaffold, Molecule
from mbforge.utils.ids import stable_id
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.persist.markush")

ROLE_SCAFFOLD = "scaffold"
ROLE_FRAGMENT = "fragment"


def delete_markush_for_doc(doc_id: str, *, conn: sqlite3.Connection) -> None:
    """Delete a document's Markush rows before a pipeline re-run writes replacements."""
    conn.execute("DELETE FROM markush_fragments WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM markush_scaffolds WHERE doc_id = ?", (doc_id,))


# ---------------------------------------------------------------------------
# Entity construction from the shared Molecule
# ---------------------------------------------------------------------------


def _coref_label(molecule: Molecule, key: str) -> str:
    """Pick the best label available on *molecule* for *key*.

    Preference order (highest first):

    1. ``normalized_label`` — the canonical form written by
       :mod:`mbforge.pipeline.detection.label_normalization`. This is the new contract.
    2. ``raw_coref_label`` — preserved verbatim from OCR. Used when the
       label is not classifiable (kind=unknown) but we still want the
       original text on disk.
    3. The legacy key (``formula_label`` / ``label``) — back-compat with
       callers that never went through the normalizer.
    4. Empty string.

    The legacy keys remain on the molecule until every caller migrates;
    this helper centralises the lookup so the SQL stays a single column.
    """
    properties = molecule.properties
    normalized = properties.get("normalized_label")
    if isinstance(normalized, str) and normalized:
        return normalized
    raw = properties.get("raw_coref_label")
    if isinstance(raw, str) and raw:
        return raw
    legacy = properties.get(key)
    if isinstance(legacy, str) and legacy:
        return legacy
    return ""


def _build_scaffold(
    doc_id: str,
    molecule: Molecule,
) -> MarkushScaffold | None:
    """Build a :class:`MarkushScaffold` entity from a pipeline candidate.

    Returns ``None`` when the candidate has no detection (the provenance
    fields are mandatory for the DB row).
    """
    detection = molecule.detections[0] if molecule.detections else None
    if detection is None:
        logger.warning(
            "Skipping Markush scaffold without a detection: doc=%s smiles=%s",
            doc_id,
            molecule.esmiles,
        )
        return None
    bbox = detection.bbox
    return MarkushScaffold(
        scaffold_id=stable_id(
            "scaffold",
            doc_id,
            molecule.canonical_smiles or "",
            str(detection.page or ""),
            *(str(v) for v in bbox) if bbox else (),  # type: ignore[arg-type]
        ),
        doc_id=doc_id,
        smiles=molecule.canonical_smiles,
        esmiles=molecule.esmiles,
        formula_label=_coref_label(molecule, "formula_label"),
        page=detection.page,
        bbox_x0=bbox[0] if bbox else None,
        bbox_y0=bbox[1] if bbox else None,
        bbox_x1=bbox[2] if bbox else None,
        bbox_y1=bbox[3] if bbox else None,
        crop_relpath=detection.image_path,
        confidence=detection.confidence,
        status=molecule.status,
        properties=dict(molecule.properties),
    )


def _build_fragment(
    doc_id: str,
    molecule: Molecule,
) -> MarkushFragment | None:
    """Build a :class:`MarkushFragment` entity from a pipeline candidate.

    Returns ``None`` when the candidate has no detection.
    """
    detection = molecule.detections[0] if molecule.detections else None
    if detection is None:
        logger.warning(
            "Skipping Markush fragment without a detection: doc=%s smiles=%s",
            doc_id,
            molecule.esmiles,
        )
        return None
    bbox = detection.bbox
    return MarkushFragment(
        fragment_id=stable_id(
            "fragment",
            doc_id,
            molecule.canonical_smiles or "",
            str(detection.page or ""),
            *(str(v) for v in bbox) if bbox else (),  # type: ignore[arg-type]
        ),
        doc_id=doc_id,
        smiles=molecule.canonical_smiles,
        esmiles=molecule.esmiles,
        label=_coref_label(molecule, "label"),
        page=detection.page,
        bbox_x0=bbox[0] if bbox else None,
        bbox_y0=bbox[1] if bbox else None,
        bbox_x1=bbox[2] if bbox else None,
        bbox_y1=bbox[3] if bbox else None,
        crop_relpath=detection.image_path,
        confidence=detection.confidence,
        status=molecule.status,
        properties=dict(molecule.properties),
    )


# ---------------------------------------------------------------------------
# SQL field order — derived from the entity's to_dict() keys.  Keeping the
# tuple in one place means adding a field to the entity automatically
# surfaces here instead of silently diverging between writer and schema.
# ---------------------------------------------------------------------------

_SCAFFOLD_COLUMNS = (
    "scaffold_id",
    "doc_id",
    "formula_label",
    "smiles",
    "esmiles",
    "page",
    "bbox_x0",
    "bbox_y0",
    "bbox_x1",
    "bbox_y1",
    "crop_relpath",
    "confidence",
    "status",
    "properties",
)

_FRAGMENT_COLUMNS = (
    "fragment_id",
    "scaffold_id",
    "doc_id",
    "label",
    "smiles",
    "esmiles",
    "page",
    "bbox_x0",
    "bbox_y0",
    "bbox_x1",
    "bbox_y1",
    "crop_relpath",
    "confidence",
    "status",
    "properties",
)


def _scaffold_values(entity: MarkushScaffold) -> tuple:
    """Return the SQL values tuple for a scaffold INSERT.

    ``properties`` is JSON-serialized; all other fields are taken
    verbatim from ``entity.to_dict()``.
    """
    d = entity.to_dict()
    d["properties"] = json.dumps(d["properties"], ensure_ascii=False)
    return tuple(d[k] for k in _SCAFFOLD_COLUMNS)


def _fragment_values(entity: MarkushFragment) -> tuple:
    """Return the SQL values tuple for a fragment INSERT.

    ``scaffold_id`` is forced to ``None`` (Phase A does not mount
    fragments on scaffolds). ``properties`` is JSON-serialized.
    """
    d = entity.to_dict()
    d["scaffold_id"] = None  # Phase A: no scaffold mounting
    d["properties"] = json.dumps(d["properties"], ensure_ascii=False)
    return tuple(d[k] for k in _FRAGMENT_COLUMNS)


# ---------------------------------------------------------------------------
# Public persist API
# ---------------------------------------------------------------------------


def persist_markush_scaffolds(
    doc_id: str,
    candidates: Iterable[Molecule],
    *,
    conn: sqlite3.Connection | None,
) -> None:
    """Insert classified scaffold candidates using the caller-owned transaction."""
    if conn is None:
        raise ValueError("persist_markush_scaffolds requires an active connection")
    placeholders = ", ".join("?" for _ in _SCAFFOLD_COLUMNS)
    sql = f"""
        INSERT INTO markush_scaffolds ({", ".join(_SCAFFOLD_COLUMNS)})
        VALUES ({placeholders})
    """
    for molecule in candidates:
        if (
            molecule.status == "rejected"
            or molecule.properties.get("structure_role") != ROLE_SCAFFOLD
        ):
            continue
        entity = _build_scaffold(doc_id, molecule)
        if entity is None:
            continue
        conn.execute(sql, _scaffold_values(entity))


def persist_markush_fragments(
    doc_id: str,
    candidates: Iterable[Molecule],
    *,
    conn: sqlite3.Connection | None,
) -> None:
    """Insert classified fragments with no scaffold mounting in Phase A."""
    if conn is None:
        raise ValueError("persist_markush_fragments requires an active connection")
    placeholders = ", ".join("?" for _ in _FRAGMENT_COLUMNS)
    sql = f"""
        INSERT INTO markush_fragments ({", ".join(_FRAGMENT_COLUMNS)})
        VALUES ({placeholders})
    """
    for molecule in candidates:
        if (
            molecule.status == "rejected"
            or molecule.properties.get("structure_role") != ROLE_FRAGMENT
        ):
            continue
        entity = _build_fragment(doc_id, molecule)
        if entity is None:
            continue
        conn.execute(sql, _fragment_values(entity))

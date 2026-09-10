"""Recorrection service for applying context-based validation to existing data.

Provides batch recorrection for molecules already persisted to the database,
and document reprocessing for documents with existing Markdown files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ...core.detection.types import DetectionSource, NormalizedMolecule
from ...pipeline.detection.correction import correct_molecules_with_context
from ...storage.sqlite.database import DatabaseManager
from ...utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RecorrectionResult:
    """Result of a molecule recorrection operation."""

    total_molecules: int = 0
    corrected_count: int = 0
    flagged_count: int = 0
    corrections: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_properties(properties_json: str | None) -> dict[str, Any]:
    """Parse properties JSON from database row."""
    if not properties_json:
        return {}
    try:
        return json.loads(properties_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _rebuild_normalized_molecule(
    row: dict[str, Any],
    detections: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> NormalizedMolecule:
    """Rebuild a NormalizedMolecule from database rows.

    Args:
        row: Row from molecules table (sqlite3.Row or dict).
        detections: Rows from molecule_detections table for this molecule.
        evidence_rows: Rows from evidence table for this molecule.

    Returns:
        A NormalizedMolecule ready for recorrection.
    """
    # Convert sqlite3.Row to dict for .get() access
    row_dict = dict(row) if hasattr(row, "keys") else row
    properties = _parse_properties(row_dict.get("properties"))

    # Merge context from evidence rows into properties
    context_texts = properties.get("context_texts", [])
    for ev in evidence_rows:
        ev_dict = dict(ev) if hasattr(ev, "keys") else ev
        ctx = ev_dict.get("context_text")
        if ctx and ctx not in context_texts:
            context_texts.append(ctx)
    if context_texts:
        properties["context_texts"] = context_texts

    # Rebuild DetectionSource list
    detection_sources: list[DetectionSource] = []
    for det in detections:
        det_dict = dict(det) if hasattr(det, "keys") else det
        detection_sources.append(
            DetectionSource(
                source="image",
                page=det_dict.get("page"),
                bbox=(
                    det_dict.get("bbox_x0"),
                    det_dict.get("bbox_y0"),
                    det_dict.get("bbox_x1"),
                    det_dict.get("bbox_y1"),
                )
                if det_dict.get("bbox_x0") is not None
                else None,
                image_path=det_dict.get("crop_relpath"),
                confidence=det_dict.get("conf_moldet", 0) or 0,
                conf_moldet=det_dict.get("conf_moldet", 0) or 0,
            )
        )

    # Map database review_status back to NormalizedMolecule status
    db_status = row_dict.get("review_status", "pending")
    if db_status == "approved":
        nm_status = "pending"  # approved molecules stay pending in corrector
    elif db_status == "rejected":
        nm_status = "rejected"
    else:
        nm_status = "pending"

    return NormalizedMolecule(
        canonical_smiles=row_dict.get("canonical_smiles") or row_dict.get("smiles", ""),
        esmiles=row_dict.get("esmiles") or row_dict.get("smiles", ""),
        name=row_dict.get("name", ""),
        sources=["image"],
        detections=detection_sources,
        status=nm_status,
        properties=properties,
    )


def _collect_corrections(molecule: NormalizedMolecule) -> list[dict[str, Any]]:
    """Collect all corrections and flags from a corrected molecule."""
    results: list[dict[str, Any]] = []
    properties = molecule.properties

    for corr in properties.get("corrections", []):
        results.append(
            {
                "type": "correction",
                "mol_id": molecule.canonical_smiles,
                "name": molecule.name,
                **corr,
            }
        )

    for flag in properties.get("review_flags", []):
        results.append(
            {
                "type": "review_flag",
                "mol_id": molecule.canonical_smiles,
                "name": molecule.name,
                **flag,
            }
        )

    return results


def recorrect_molecules(
    library_root: str,
    doc_id: str | None = None,
    dry_run: bool = True,
) -> RecorrectionResult:
    """Recorrect molecules in the database using context-based rules.

    Args:
        library_root: Project root directory.
        doc_id: Optional document ID to filter molecules. None = all documents.
        dry_run: If True, only report corrections without updating database.

    Returns:
        RecorrectionResult with statistics and correction details.
    """
    db = DatabaseManager.get(library_root)
    db.initialize()

    result = RecorrectionResult()

    # Build query
    if doc_id:
        molecules_query = """
            SELECT DISTINCT m.* FROM molecules m
            JOIN molecule_detections md ON m.mol_id = md.mol_id
            WHERE md.doc_id = ?
        """
        params = (doc_id,)
    else:
        molecules_query = "SELECT * FROM molecules"
        params = ()

    molecules_rows = db.execute(molecules_query, params, db="mol")
    result.total_molecules = len(molecules_rows)

    if not molecules_rows:
        logger.info("No molecules found for recorrection")
        return result

    # Rebuild NormalizedMolecule objects
    molecules_to_correct: list[NormalizedMolecule] = []
    mol_id_map: dict[str, str] = {}  # canonical_smiles -> mol_id

    mol_ids: list[str] = []
    canonicals: list[str] = []
    for row in molecules_rows:
        row_dict = dict(row) if hasattr(row, "keys") else row
        mol_ids.append(row_dict["mol_id"])
        canonicals.append(
            row_dict.get("canonical_smiles") or row_dict.get("smiles", "")
        )

    # Batch-fetch detections and evidence, then group by molecule.
    placeholders = ",".join("?" * len(mol_ids))
    detections_rows = db.execute(
        f"SELECT * FROM molecule_detections WHERE mol_id IN ({placeholders})",
        mol_ids,
        db="mol",
    )
    detections_by_mol: dict[str, list[Any]] = {mol_id: [] for mol_id in mol_ids}
    for det in detections_rows:
        detections_by_mol[det["mol_id"]].append(det)

    canonical_placeholders = ",".join("?" * len(canonicals))
    evidence_rows = db.execute(
        f"""
        SELECT * FROM evidence
        WHERE mol_id IN ({placeholders}) OR canonical_smiles IN ({canonical_placeholders})
        """,
        mol_ids + canonicals,
        db="mol",
    )
    evidence_by_mol: dict[str, list[Any]] = {mol_id: [] for mol_id in mol_ids}
    evidence_by_canonical: dict[str, list[Any]] = {}
    for ev in evidence_rows:
        ev_mol_id = ev["mol_id"]
        ev_canonical = ev["canonical_smiles"]
        if ev_mol_id is not None and ev_mol_id in evidence_by_mol:
            evidence_by_mol[ev_mol_id].append(ev)
        if ev_canonical is not None:
            evidence_by_canonical.setdefault(ev_canonical, []).append(ev)

    for row, canonical in zip(molecules_rows, canonicals, strict=False):
        row_dict = dict(row) if hasattr(row, "keys") else row
        mol_id = row_dict["mol_id"]
        mol_id_map[canonical] = mol_id

        detections = detections_by_mol.get(mol_id, [])
        mol_evidence = evidence_by_mol.get(mol_id, [])
        if canonical in evidence_by_canonical:
            mol_evidence = mol_evidence + evidence_by_canonical[canonical]

        # Deduplicate rows that matched both mol_id and canonical_smiles.
        seen_ids: set[int] = set()
        deduped_evidence: list[Any] = []
        for ev in mol_evidence:
            ev_id = ev["id"]
            if ev_id not in seen_ids:
                seen_ids.add(ev_id)
                deduped_evidence.append(ev)

        nm = _rebuild_normalized_molecule(row, detections, deduped_evidence)
        molecules_to_correct.append(nm)

    # Run corrections
    corrected = correct_molecules_with_context(molecules_to_correct)

    # Collect results
    for nm in corrected:
        corrections = _collect_corrections(nm)
        if corrections:
            result.corrected_count += 1
            result.corrections.extend(corrections)
        if nm.properties.get("review_flags"):
            result.flagged_count += 1

    # Update database if not dry run
    if not dry_run and result.corrected_count > 0:
        _apply_corrections_to_db(db, corrected, mol_id_map)

    logger.info(
        "Recorrection complete: %d/%d molecules corrected, %d flagged",
        result.corrected_count,
        result.total_molecules,
        result.flagged_count,
    )

    return result


def _apply_corrections_to_db(
    db: DatabaseManager,
    molecules: list[NormalizedMolecule],
    mol_id_map: dict[str, str],
) -> None:
    """Apply corrections to the database.

    Updates molecules.properties with corrections and review_flags,
    and updates review_status based on correction results.
    """
    with db.transaction() as (kb_conn, mol_conn):
        conn = mol_conn  # Use the molecule connection
        for nm in molecules:
            canonical = nm.canonical_smiles
            mol_id = mol_id_map.get(canonical)
            if not mol_id:
                continue

            # Serialize updated properties
            properties_json = json.dumps(nm.properties, ensure_ascii=False)

            # Determine new review_status
            # If molecule has corrections that changed status to pending_review,
            # set review_status to 'pending' (needs review)
            # Otherwise keep existing status
            new_status = "pending"  # Default: needs review after recorrection

            conn.execute(
                """
                UPDATE molecules
                SET properties = ?, review_status = ?, reviewed_at = NULL
                WHERE mol_id = ?
                """,
                (properties_json, new_status, mol_id),
            )

            # Log to molecule_corrections table
            for corr in nm.properties.get("corrections", []):
                conn.execute(
                    """
                    INSERT INTO molecule_corrections
                    (mol_id, field, old_value, new_value, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mol_id,
                        corr.get("rule", "unknown"),
                        corr.get("original", ""),
                        corr.get("corrected", ""),
                        "recorrection_service",
                        corr.get("timestamp", datetime.now(UTC).isoformat()),
                    ),
                )

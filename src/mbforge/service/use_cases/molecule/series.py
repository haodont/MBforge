"""Assemble a structure-activity series: each molecule joined to its readings.

The molecule-centric inverse of the document activity list. SAR reasoning needs
every candidate structure with its own attributed activities, evidence refs and
review state in one row, instead of correlating ``search_molecules`` and
``query_activities`` by id across pages. A series member with no measured
activity is kept (an empty activity list is itself a SAR fact); a reading no
structure owns never leaks into a molecule.
"""

from __future__ import annotations

from typing import Any

from mbforge.contracts.molecule import MoleculeListRequest
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.activity_queries import effective_attribution
from mbforge.service.use_cases.documents.structure_verification import (
    verify_structures as verify_document_structures,
)
from mbforge.service.use_cases.molecule.queries import (
    normalize_molecule_row,
    resolve_search_mode,
    search_molecules,
)

#: A series row needs the whole document's structure facts, not one page of them.
_ALL_STRUCTURES = 100000

#: ``measured_only`` scans this many molecules before paging over the measured ones.
_MEASURED_SCAN_CAP = 5000


def _structure_facts(
    library_root: str, doc_ids: list[str]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Map (document, mol_id) to the drawing's page, bbox, evidence id and mass verdict.

    Reuses the verification pass the ``verify_structures`` capability runs, so a
    series row cites the same structure evidence that tool reports. The pass is
    per document and cached for the whole page, not per molecule.
    """
    facts: dict[tuple[str, str], dict[str, Any]] = {}
    for doc_id in dict.fromkeys(doc_ids):
        if not doc_id:
            continue
        data = verify_document_structures(library_root, doc_id, limit=_ALL_STRUCTURES)
        for row in data.get("items", []):
            mol_id = str(row.get("mol_id") or "")
            if mol_id:
                facts[(doc_id, mol_id)] = row
    return facts


def _select_molecules(
    library_root: str,
    *,
    doc_id: str,
    query: str,
    mode: str,
    similarity_threshold: float,
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    """Pick the series members: a structure search, or a document's molecules."""
    if query:
        resolved = resolve_search_mode(query, mode)
        rows = search_molecules(
            library_root,
            query,
            top_k,
            resolved,
            similarity_threshold,
            doc_id=doc_id,
        )
        return rows, resolved
    page = get_repositories(library_root).molecules.list_page(
        MoleculeListRequest(
            library_root=library_root,
            source_doc=doc_id,
            page=1,
            page_size=top_k,
        )
    )
    return [normalize_molecule_row(row) for row in page["rows"]], ""


def _shape_activities(
    rows: list[dict[str, Any]], mol_id: str, *, metric: str, target: str
) -> list[dict[str, Any]]:
    """One row per reading attributed to this molecule, best link winning."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["measurement_id"]), []).append(row)
    activities: list[dict[str, Any]] = []
    for links in grouped.values():
        row = links[0]
        if metric and str(row.get("metric") or "").lower() != metric.lower():
            continue
        if target and target.lower() not in str(row.get("target") or "").lower():
            continue
        best = (
            effective_attribution(
                [
                    {
                        "mol_id": mol_id,
                        "method": link.get("attribution_method"),
                        "confidence": link.get("attribution_confidence"),
                        "review_status": link.get("attribution_review_status"),
                        "evidence_id": link.get("attribution_evidence_id"),
                    }
                    for link in links
                ]
            )
            or {}
        )
        activities.append(
            {
                "measurement_id": str(row["measurement_id"]),
                "metric": str(row.get("metric") or ""),
                "target": str(row.get("target") or ""),
                "species": str(row.get("species") or ""),
                "assay_type": str(row.get("assay_type") or ""),
                "assay_description": str(row.get("assay_description") or ""),
                "value_canonical": row.get("canonical_value"),
                "unit_canonical": str(row.get("canonical_unit") or ""),
                "value_original": row.get("original_value"),
                "unit_original": str(row.get("original_unit") or ""),
                "operator": str(row.get("operator") or ""),
                "value_text": str(row.get("value_text") or ""),
                "page_num": row.get("page_num"),
                "table_idx": row.get("table_idx"),
                "row_idx": row.get("row_idx"),
                "evidence_ids": row.get("evidence_ids") or [],
                "evidence_grade": str(row.get("evidence_grade") or ""),
                "review_status": str(row.get("review_status") or "pending"),
                "attribution_method": str(best.get("method") or ""),
                "attribution_confidence": best.get("confidence"),
                "attribution_review_status": str(best.get("review_status") or ""),
            }
        )
    activities.sort(
        key=lambda item: (
            item["page_num"] if item["page_num"] is not None else 10**9,
            item["table_idx"] if item["table_idx"] is not None else 10**9,
            item["row_idx"] if item["row_idx"] is not None else 10**9,
            item["measurement_id"],
        )
    )
    return activities


def analyze_series(
    library_root: str | None,
    *,
    doc_id: str = "",
    query: str = "",
    mode: str = "auto",
    similarity_threshold: float = 0.5,
    metric: str = "",
    target: str = "",
    offset: int = 0,
    limit: int = 20,
    measured_only: bool = False,
) -> dict[str, Any]:
    """Return a page of molecules, each carrying its attributed activity series.

    ``measured_only`` pages over molecules that own at least one reading for the
    requested metric instead of over every structure in scope, so a document with
    hundreds of intermediates still yields one page of measured compounds. The
    molecules dropped by that filter are counted in ``unmeasured`` rather than
    silently vanishing.
    """
    if not library_root or not (doc_id or query):
        return {
            "items": [],
            "resolved_mode": "",
            "truncated": False,
            "next_offset": None,
            "unmeasured": 0,
        }
    scan = _MEASURED_SCAN_CAP if measured_only else offset + limit + 1
    rows, resolved = _select_molecules(
        library_root,
        doc_id=doc_id,
        query=query,
        mode=mode,
        similarity_threshold=similarity_threshold,
        top_k=scan,
    )
    by_mol = get_repositories(library_root).measurements.measurements_for_molecules(
        [str(row.get("mol_id") or row.get("canonical_smiles") or "") for row in rows]
    )
    selected: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for row in rows:
        mol_id = str(row.get("mol_id") or row.get("canonical_smiles") or "")
        activities = _shape_activities(
            by_mol.get(mol_id, []), mol_id, metric=metric, target=target
        )
        if measured_only and not activities:
            continue
        selected.append((row, activities))
    unmeasured = len(rows) - len(selected) if measured_only else 0
    page = selected[offset : offset + limit]
    truncated = len(selected) > offset + limit
    facts = _structure_facts(
        library_root,
        [str(row.get("source_doc") or "") for row, _ in page],
    )
    items: list[dict[str, Any]] = []
    for row, activities in page:
        mol_id = str(row.get("mol_id") or row.get("canonical_smiles") or "")
        canonical = str(row.get("canonical_smiles") or row.get("smiles") or "")
        esmiles = str(row.get("esmiles") or "")
        properties = row.get("properties") or {}
        similarity = row.get("similarity")
        source_doc = str(row.get("source_doc") or "")
        structure = facts.get((source_doc, mol_id), {})
        items.append(
            {
                "mol_id": mol_id or canonical,
                "canonical_smiles": canonical,
                "esmiles": esmiles if esmiles and esmiles != canonical else "",
                "name": str(row.get("name") or ""),
                "review_status": str(row.get("review_status") or "pending"),
                "structure_role": str(properties.get("structure_role") or ""),
                "source_doc": row.get("source_doc") or None,
                "similarity": float(similarity) if similarity is not None else None,
                # The drawing this molecule's SMILES was read from: the second
                # half of a citation, beside the reading's evidence ids below.
                "structure_evidence_id": str(structure.get("evidence_id") or ""),
                "structure_page": structure.get("page"),
                "structure_bbox": structure.get("bbox"),
                "mass_check": str(structure.get("mass_check") or ""),
                "activities": activities,
            }
        )
    return {
        "items": items,
        "resolved_mode": resolved,
        "truncated": truncated,
        "next_offset": offset + limit if truncated else None,
        "unmeasured": unmeasured,
    }


__all__ = ["analyze_series"]

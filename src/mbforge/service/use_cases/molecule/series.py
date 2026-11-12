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
from mbforge.service.use_cases.molecule.queries import (
    normalize_molecule_row,
    resolve_search_mode,
    search_molecules,
)


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
) -> dict[str, Any]:
    """Return a page of molecules, each carrying its attributed activity series."""
    if not library_root or not (doc_id or query):
        return {
            "items": [],
            "resolved_mode": "",
            "truncated": False,
            "next_offset": None,
        }
    rows, resolved = _select_molecules(
        library_root,
        doc_id=doc_id,
        query=query,
        mode=mode,
        similarity_threshold=similarity_threshold,
        top_k=offset + limit + 1,
    )
    page = rows[offset : offset + limit]
    truncated = len(rows) > offset + limit
    mol_ids = [
        str(row.get("mol_id") or row.get("canonical_smiles") or "") for row in page
    ]
    by_mol = get_repositories(library_root).measurements.measurements_for_molecules(
        [mol_id for mol_id in mol_ids if mol_id]
    )
    items: list[dict[str, Any]] = []
    for row, mol_id in zip(page, mol_ids, strict=True):
        canonical = str(row.get("canonical_smiles") or row.get("smiles") or "")
        esmiles = str(row.get("esmiles") or "")
        properties = row.get("properties") or {}
        similarity = row.get("similarity")
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
                "activities": _shape_activities(
                    by_mol.get(mol_id, []), mol_id, metric=metric, target=target
                ),
            }
        )
    return {
        "items": items,
        "resolved_mode": resolved,
        "truncated": truncated,
        "next_offset": offset + limit if truncated else None,
    }


__all__ = ["analyze_series"]

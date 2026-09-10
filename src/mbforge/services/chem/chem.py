"""Cheminformatics operations — RDKit wrappers for the chem endpoints.

Business logic extracted from ``routers/molecule/chem.py``; the router
stays a thin async shell. Functions accept/return ``models.chem`` types
so the HTTP contract is unchanged.
"""

from __future__ import annotations

from typing import Any

from ...core.entities.molecule import Molecule
from ...models.chem import (
    CanonicalizeResponse,
    FingerprintResponse,
    MoleculeProperties,
    PropertiesResponse,
    SimilaritySearchRequest,
    SimilaritySearchResponse,
    SubstructureSearchRequest,
    SubstructureSearchResponse,
    TanimotoResponse,
    ValidateSmilesResponse,
)
from ..molecule.queries import similarity_search_db, substructure_search_db


def validate_smiles_sync(items: list[str]) -> list[ValidateSmilesResponse]:
    """Batch validate SMILES strings against RDKit."""

    def _one(smiles: str) -> ValidateSmilesResponse:
        try:
            from rdkit import Chem

            mol = Chem.MolFromSmiles(smiles)
            canonical = Chem.MolToSmiles(mol) if mol is not None else None
            return ValidateSmilesResponse(
                input=smiles,
                valid=mol is not None,
                canonical_smiles=canonical,
                smiles=smiles,
            )
        except Exception as e:
            return ValidateSmilesResponse(
                input=smiles, valid=False, smiles=smiles, error=str(e)
            )

    return [_one(s) for s in items]


def fingerprint_sync(smiles: str) -> FingerprintResponse:
    try:
        import numpy as np
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return FingerprintResponse(success=False, error="invalid SMILES")
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
        arr = np.array(fp, dtype=np.uint8)
        return FingerprintResponse(
            success=True, fingerprint=arr.tolist(), bits=int(arr.sum())
        )
    except Exception as e:
        return FingerprintResponse(success=False, error=str(e))


def tanimoto_sync(fp_a: list[int], fp_b: list[int]) -> TanimotoResponse:
    a = {i for i, v in enumerate(fp_a) if v}
    b = {i for i, v in enumerate(fp_b) if v}
    if not a and not b:
        return TanimotoResponse(success=True, similarity=1.0)
    intersection = len(a & b)
    union = len(a | b)
    return TanimotoResponse(
        success=True, similarity=intersection / union if union else 0.0
    )


def properties_sync(smiles: str) -> PropertiesResponse:
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, rdMolDescriptors

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return PropertiesResponse(success=False, error="invalid SMILES")
        return PropertiesResponse(
            success=True,
            properties=MoleculeProperties(
                molecular_weight=round(Descriptors.MolWt(mol), 2),
                logp=round(Descriptors.MolLogP(mol), 2),
                hbd=rdMolDescriptors.CalcNumHBD(mol),
                hba=rdMolDescriptors.CalcNumHBA(mol),
                tpsa=round(Descriptors.TPSA(mol), 2),
                rotatable_bonds=rdMolDescriptors.CalcNumRotatableBonds(mol),
                aromatic_rings=rdMolDescriptors.CalcNumAromaticRings(mol),
                formula=rdMolDescriptors.CalcMolFormula(mol),
            ),
        )
    except Exception as e:
        return PropertiesResponse(success=False, error=str(e))


def canonicalize_sync(smiles: str) -> CanonicalizeResponse:
    try:
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return CanonicalizeResponse(success=False, error="invalid SMILES")
        return CanonicalizeResponse(success=True, result=Chem.MolToSmiles(mol))
    except Exception as e:
        return CanonicalizeResponse(success=False, error=str(e))


def draw_smiles_sync(smiles: str, width: int, height: int):
    """Render a SMILES or Markush structure with local RDKit as SVG."""
    from ...models.chem import SmilesImageResponse

    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return SmilesImageResponse(success=False, error="invalid SMILES")
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
        drawer.FinishDrawing()
        return SmilesImageResponse(success=True, svg=drawer.GetDrawingText())
    except Exception as e:
        return SmilesImageResponse(success=False, error=str(e))


def markush_parse_sync(smiles: str) -> dict:
    """Parse a Markush SMILES into the core + explicit attachment sites."""
    from ...core.markush.parser import parse_markush, parse_response

    parsed = parse_markush(smiles)
    return parse_response(parsed)


def markush_check_sync(esmiles: str, query: str) -> dict:
    """Check whether *query* falls within a Markush pattern's scope."""
    from ...core.markush.coverage import check_markush_coverage, check_response
    from ...core.markush.parser import parse_markush

    parsed = parse_markush(esmiles)
    match_level, site_results, details, ratio = check_markush_coverage(parsed, query)
    return check_response(match_level, site_results, details, ratio)


def _candidate_smiles(candidate: object) -> str | None:
    """Extract a SMILES string from a dict or object candidate."""
    if isinstance(candidate, dict):
        return candidate.get("smiles") or candidate.get("canonical_smiles")
    return getattr(candidate, "smiles", None) or getattr(
        candidate, "canonical_smiles", None
    )


def substructure_search_sync(
    body: SubstructureSearchRequest,
) -> SubstructureSearchResponse:
    from rdkit import Chem

    query_mol = Chem.MolFromSmiles(body.query)
    if query_mol is None:
        return SubstructureSearchResponse(
            success=False, error="invalid query SMILES", results=[]
        )

    candidates = body.candidates or []
    if candidates:
        results: list[Any] = []
        for candidate in candidates:
            smiles = _candidate_smiles(candidate)
            if not smiles:
                continue
            mol = Chem.MolFromSmiles(smiles)
            if mol is not None and mol.HasSubstructMatch(query_mol):
                results.append(candidate)
                if len(results) >= body.top_k:
                    break
        return SubstructureSearchResponse(results=results)

    if body.library_root:
        results = substructure_search_db(body.library_root, body.query, body.top_k)
        return SubstructureSearchResponse(results=results)

    return SubstructureSearchResponse(
        success=False,
        error="candidates or library_root is required",
        results=[],
    )


def similarity_search_sync(
    body: SimilaritySearchRequest,
) -> SimilaritySearchResponse:
    query_mol = Molecule(mol_id="", canonical_smiles=body.query)
    query_fp = query_mol.fingerprint
    if query_fp is None:
        return SimilaritySearchResponse(
            success=False, error="invalid query SMILES", results=[]
        )

    candidates = body.candidates or []
    if candidates:
        scored: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            smiles = _candidate_smiles(candidate)
            if not smiles:
                continue
            candidate_mol = Molecule(mol_id="", canonical_smiles=smiles)
            candidate_fp = candidate_mol.fingerprint
            if candidate_fp is None:
                continue
            similarity = Molecule.tanimoto_bytes(query_fp, candidate_fp)
            if similarity >= body.threshold:
                item = dict(candidate) if isinstance(candidate, dict) else {}
                item["similarity"] = similarity
                scored.append((similarity, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return SimilaritySearchResponse(
            results=[item for _, item in scored[: body.top_k]]
        )

    if body.library_root:
        results = similarity_search_db(
            body.library_root, body.query, body.top_k, body.threshold
        )
        return SimilaritySearchResponse(results=results)

    return SimilaritySearchResponse(
        success=False,
        error="candidates or library_root is required",
        results=[],
    )


def render_molecule_png_sync(smiles: str, width: int, height: int) -> dict:
    """Render a molecule to a base64 PNG (sync) for /models/mol/render."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Draw

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return {"success": False, "error": "Invalid SMILES"}

        img = Draw.MolToImage(mol, size=(width, height))
        import base64
        import io

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return {"success": True, "image_base64": img_b64}
    except Exception as e:
        from ...utils.logger import get_logger

        get_logger(__name__).error("Molecule render failed: %s", e)
        return {"success": False, "error": str(e)}

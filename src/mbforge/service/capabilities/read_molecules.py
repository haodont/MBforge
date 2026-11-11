"""Read-only molecule search capability exposed to agents.

Split from ``capabilities.read`` by responsibility.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from mbforge.service.capabilities.registry import (
    DOC_ID_DESCRIPTION,
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.molecule.queries import (
    resolve_search_mode,
    search_molecules,
)


class SearchMoleculesInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    mode: Literal["auto", "text", "substructure", "similarity"] = "auto"
    doc_id: str = Field("", max_length=128, description=DOC_ID_DESCRIPTION)
    offset: int = Field(0, ge=0)
    limit: int = Field(10, ge=1, le=50)
    similarity_threshold: float = Field(0.5, ge=0.0, le=1.0)


class MoleculeHit(BaseModel):
    """One molecule library row, deduplicated.

    ``mol_id`` is the canonical SMILES by pipeline convention, so it is never a
    second copy of ``canonical_smiles``; ``esmiles`` is only included when the
    recognizer kept an extension form that differs from the canonical one.
    Activity values are not carried here — ``query_activities`` is the
    authoritative activity reading.
    """

    mol_id: str
    canonical_smiles: str
    esmiles: str = ""
    name: str = ""
    review_status: str = "pending"
    source_doc: str | None = None
    similarity: float | None = None


class SearchMoleculesOutput(BaseModel):
    """The search decision plus the page of hits.

    ``resolved_mode`` is what ``auto`` actually ran. ``threshold_applied`` is
    the only case in which ``similarity_threshold`` filtered anything: an empty
    page with it false means the query matched nothing, and with it true the
    near-misses were dropped — re-run with ``similarity_threshold=0.0`` to list
    every scored candidate with its ``similarity``.
    """

    query: str
    requested_mode: Literal["auto", "text", "substructure", "similarity"]
    resolved_mode: Literal["text", "substructure", "similarity"]
    doc_id: str = ""
    short_id: str = ""
    similarity_threshold: float
    threshold_applied: bool
    items: list[MoleculeHit] = Field(default_factory=list)


def _molecule_hit(row: dict[str, Any]) -> MoleculeHit:
    """Project one molecule row onto the deduplicated hit contract."""
    canonical = str(row.get("canonical_smiles") or row.get("smiles") or "")
    mol_id = str(row.get("mol_id") or canonical)
    esmiles = str(row.get("esmiles") or "")
    similarity = row.get("similarity")
    return MoleculeHit(
        mol_id=mol_id,
        canonical_smiles=canonical,
        esmiles=esmiles if esmiles and esmiles != canonical else "",
        name=str(row.get("name") or ""),
        review_status=str(row.get("review_status") or "pending"),
        source_doc=row.get("source_doc") or None,
        similarity=float(similarity) if similarity is not None else None,
    )


async def search_molecules_capability(
    context: CapabilityContext, request: SearchMoleculesInput
) -> CapabilityResult:
    resolved = resolve_search_mode(request.query, request.mode)
    rows = await asyncio.to_thread(
        search_molecules,
        context.library_root,
        request.query,
        request.offset + request.limit + 1,
        resolved,
        request.similarity_threshold,
        doc_id=request.doc_id,
    )
    page = rows[request.offset : request.offset + request.limit]
    next_offset = (
        request.offset + request.limit
        if len(rows) > request.offset + request.limit
        else None
    )
    return CapabilityResult(
        data=SearchMoleculesOutput(
            query=request.query,
            requested_mode=request.mode,
            resolved_mode=resolved,
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id) if request.doc_id else "",
            similarity_threshold=request.similarity_threshold,
            threshold_applied=resolved == "similarity"
            and request.similarity_threshold > 0,
            items=[_molecule_hit(row) for row in page],
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


register(
    Capability(
        name="search_molecules",
        description=(
            "Search the molecule library by text, substructure or similarity, "
            "optionally scoped to one document. The response echoes "
            "resolved_mode — what mode=auto actually ran (a parseable SMILES "
            "takes the substructure path, never similarity) — and "
            "threshold_applied says whether similarity_threshold filtered "
            "anything, so an empty page is distinguishable from a threshold cut. "
            "Hits carry one canonical SMILES and its similarity when scored; "
            "activity values come from query_activities, not here."
        ),
        input_model=SearchMoleculesInput,
        output_model=SearchMoleculesOutput,
        mutating=False,
        handler=search_molecules_capability,
    )
)

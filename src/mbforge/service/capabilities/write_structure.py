"""Agent promotion of one recognized drawing into the concrete library.

The role gate withholds a closed, labelled drawing when the prose around it
looks generic, which is right, but the withheld drawing then has no way back:
no ``molecules`` row means no reading can be linked to it. This capability is
the decision path back — one drawing, its evidence, and a recorded reason.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from mbforge.foundation.errors import NotFoundError
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    doc_id_field,
    register,
)
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.documents.structure_promotion import promote_structure


class PromoteStructureInput(BaseModel):
    doc_id: str = doc_id_field()
    smiles: str = Field(
        "",
        max_length=2048,
        description=(
            "Canonical SMILES of the drawing to promote, as reported by "
            "verify_structures or get_binding_candidates."
        ),
    )
    evidence_id: str = Field(
        "",
        max_length=128,
        description="Molecule evidence id of that drawing (alternative to smiles).",
    )
    reason: str = Field(
        "",
        max_length=1000,
        description=(
            "Why this drawing is a concrete compound, not a generic structure: "
            "the printed designation, the section that prepares it, the printed "
            "mass. Stored on the molecule."
        ),
    )


class PromoteStructureOutput(BaseModel):
    doc_id: str
    short_id: str
    mol_id: str
    name: str
    page: int | None = None
    promoted: bool
    structure_role: str = "complete"


async def promote_structure_capability(
    context: CapabilityContext, request: PromoteStructureInput
) -> CapabilityResult:
    """Promote one drawing to a concrete structure, or report why not."""
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)

    result = await asyncio.to_thread(
        promote_structure,
        context.library_root,
        request.doc_id,
        smiles=request.smiles,
        evidence_id=request.evidence_id,
        reason=request.reason,
    )
    return CapabilityResult(
        data=PromoteStructureOutput(
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id),
            **result,
        )
    )


register(
    Capability(
        name="promote_structure",
        description=(
            "Promote ONE recognized drawing to a concrete stored structure when "
            "the Markush role gate withheld it, so readings can be linked to it. "
            "The drawing must already exist in the document's molecule evidence; "
            "a scaffold, a fragment with a dummy atom, or a rejected structure is "
            "refused. Idempotent: an already stored structure reports "
            "promoted=false. Use assign_attributions afterwards for the links."
        ),
        input_model=PromoteStructureInput,
        output_model=PromoteStructureOutput,
        mutating=True,
        handler=promote_structure_capability,
    )
)

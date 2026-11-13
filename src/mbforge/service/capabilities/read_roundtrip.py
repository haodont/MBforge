"""Round-trip structure verification — the read-only visual check.

Split from ``read_structures`` by responsibility: that file owns the printed
mass delta, this one owns drawing a stored SMILES back and reading it again.
"""

from __future__ import annotations

import asyncio
from typing import Literal

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
from mbforge.service.use_cases.documents.structure_roundtrip import (
    verify_structure_roundtrip as verify_roundtrip_use_case,
)


class VerifyRoundTripInput(BaseModel):
    doc_id: str = doc_id_field()
    evidence_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "The molecule evidence row to verify — the evidence_id a "
            "verify_structures row or a list_evidence molecule row carries."
        ),
    )


class VerifyRoundTripOutput(BaseModel):
    doc_id: str
    short_id: str
    evidence_id: str
    mol_id: str = ""
    page: int | None = None
    bbox: list[float] | None = None
    smiles: str = ""
    canonical_smiles: str = ""
    self_consistency: Literal[
        "consistent", "graph_consistent", "divergent", "unreadable", "not_renderable"
    ]
    recovered_smiles: str = ""
    recovered_canonical: str = ""
    #: What the recognizer reads in the original crop now; "" without a crop.
    crop_smiles: str = ""
    #: Whether the drawing reads back as what the original crop reads as —
    #: the layout-invariant fidelity signal. no_crop when the PDF is unavailable.
    crop_consistency: Literal[
        "consistent", "graph_consistent", "divergent", "unreadable", "no_crop"
    ] = "no_crop"
    #: The RDKit drawing of the stored SMILES, for looking at alongside the crop.
    image_base64: str | None = None
    notes: list[str] = Field(default_factory=list)


async def verify_structure_roundtrip(
    context: CapabilityContext, request: VerifyRoundTripInput
) -> CapabilityResult:
    """Draw one stored structure's SMILES and read the drawing back.

    Reports whether the drawing reads back as the stored molecule, and whether
    it reads back as what the original crop reads as. Both are evidence for a
    human, never a correction; nothing is written.
    """
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)

    report = await asyncio.to_thread(
        verify_roundtrip_use_case,
        context.library_root,
        request.doc_id,
        request.evidence_id,
    )
    return CapabilityResult(
        data=VerifyRoundTripOutput(
            **report,
            short_id=short_doc_id(report["doc_id"]),
        )
    )


register(
    Capability(
        name="verify_structure_roundtrip",
        description=(
            "Visual round-trip check for one recognized structure: draw its "
            "stored SMILES back with RDKit, read the drawing with MolParser, "
            "and read the original crop again. Reports (1) self_consistency — "
            "whether the drawing reads back as the stored molecule (consistent "
            "/ graph_consistent / divergent / unreadable / not_renderable; "
            "Markush scaffolds compare under the recognizer's dummy-as-methyl "
            "convention) — and (2) crop_consistency, whether the drawing reads "
            "back as what the original crop reads as: the layout-invariant "
            "fidelity signal. The returned image_base64 is the drawing, to "
            "compare against the original via molecule_image. Read-only: both "
            "signals are evidence for a human, never a correction, and both "
            "reads share one recognizer, so the printed-mass delta from "
            "verify_structures remains the independent evidence. Chain from "
            "verify_structures, which lists each structure's evidence_id."
        ),
        input_model=VerifyRoundTripInput,
        output_model=VerifyRoundTripOutput,
        mutating=False,
        handler=verify_structure_roundtrip,
    )
)

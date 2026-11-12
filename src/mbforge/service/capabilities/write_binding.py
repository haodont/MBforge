"""Agent attribution — the mutating capability for the agent's own adjudication.

Where ``propose_review`` files a suggestion a human must confirm, this
capability writes the agent's accepted decision: a ``reading -> structure``
link with ``method="agent"``. It is the L2 write path of the binding design —
the agent applies the high-confidence adjudications (R1–R5) itself, and a
human link still outranks it.

The write is validated, not blind: the reading must exist in this document and
the structure must be a stored molecule. An attribution that names neither is
a guess, and a guess is what the review queue exists for.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from mbforge.contracts.measurement import MeasurementQuery
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


class AssignAttributionInput(BaseModel):
    doc_id: str = doc_id_field()
    measurement_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="The printed reading the decision is about.",
    )
    mol_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "The molecule the reading resolves to: its stored id, which for a "
            "detected structure is the canonical SMILES."
        ),
    )
    evidence_id: str = Field(
        "",
        max_length=128,
        description="Structure evidence id that supports the decision.",
    )
    confidence: float | None = Field(
        None,
        ge=0,
        le=1,
        description="Optional confidence for the adjudication.",
    )


class AssignAttributionOutput(BaseModel):
    attribution_id: str
    doc_id: str
    short_id: str
    measurement_id: str
    mol_id: str
    method: str
    confidence: float | None = None
    evidence_id: str = ""
    review_status: str


async def assign_attribution(
    context: CapabilityContext, request: AssignAttributionInput
) -> CapabilityResult:
    """Write one agent-decided reading -> structure link."""
    from mbforge.service.ports import get_repositories

    root = context.library_root
    store = LibraryStore.get(root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)

    repositories = get_repositories(root)
    readings = await asyncio.to_thread(
        repositories.measurements.list,
        MeasurementQuery(doc_id=request.doc_id, limit=1000),
    )
    if not any(row["measurement_id"] == request.measurement_id for row in readings):
        raise NotFoundError("measurement not found", detail=request.measurement_id)
    identity = await asyncio.to_thread(
        repositories.molecules.identity_fields, [request.mol_id]
    )
    if request.mol_id not in identity:
        raise NotFoundError("molecule not found", detail=request.mol_id)

    attribution_id = await asyncio.to_thread(
        repositories.measurements.bind_attribution,
        measurement_id=request.measurement_id,
        mol_id=request.mol_id,
        doc_id=request.doc_id,
        evidence_id=request.evidence_id,
        method="agent",
        confidence=request.confidence,
    )
    return CapabilityResult(
        data=AssignAttributionOutput(
            attribution_id=attribution_id,
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id),
            measurement_id=request.measurement_id,
            mol_id=request.mol_id,
            method="agent",
            confidence=request.confidence,
            evidence_id=request.evidence_id,
            review_status="accepted",
        )
    )


register(
    Capability(
        name="assign_attribution",
        description=(
            "Write the agent's own structure-activity adjudication: one "
            "reading -> structure link with method=agent, accepted on write. "
            "A human link outranks it (human > agent > rule). The reading must "
            "exist in the document and the structure must be a stored molecule; "
            "anything uncertain belongs in the review queue, not here."
        ),
        input_model=AssignAttributionInput,
        output_model=AssignAttributionOutput,
        mutating=True,
        handler=assign_attribution,
    )
)

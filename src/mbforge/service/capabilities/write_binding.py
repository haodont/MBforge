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


class AttributionDecision(BaseModel):
    """One reading -> structure decision inside a batch."""

    measurement_id: str = Field(..., min_length=1, max_length=128)
    mol_id: str = Field(..., min_length=1, max_length=128)
    evidence_id: str = Field("", max_length=128)
    confidence: float | None = Field(None, ge=0, le=1)


class AssignAttributionsInput(BaseModel):
    doc_id: str = doc_id_field()
    decisions: list[AttributionDecision] = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "The adjudications this pass decided. Every reading must exist in "
            "the document and every structure must be a stored molecule: one "
            "unverifiable decision rejects the whole batch, so a partial write "
            "never looks like a finished pass."
        ),
    )


class AssignAttributionsOutput(BaseModel):
    doc_id: str
    short_id: str
    written: list[AssignAttributionOutput] = Field(default_factory=list)
    count: int
    method: str = "agent"


async def assign_attributions(
    context: CapabilityContext, request: AssignAttributionsInput
) -> CapabilityResult:
    """Write a batch of agent-decided reading -> structure links.

    One inspection pass usually settles tens of readings, and writing them one
    tool call at a time is what made the agent stop halfway. The batch is
    validated as a whole before anything is written: a decision that names a
    reading from another document or a structure the library does not hold
    rejects the batch instead of leaving a half-applied adjudication behind.
    """
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
    known_readings = {str(row["measurement_id"]) for row in readings}
    missing_readings = [
        decision.measurement_id
        for decision in request.decisions
        if decision.measurement_id not in known_readings
    ]
    if missing_readings:
        raise NotFoundError(
            "measurement not found", detail=", ".join(sorted(set(missing_readings)))
        )
    mol_ids = list(dict.fromkeys(decision.mol_id for decision in request.decisions))
    identity = await asyncio.to_thread(repositories.molecules.identity_fields, mol_ids)
    missing_molecules = [mol_id for mol_id in mol_ids if mol_id not in identity]
    if missing_molecules:
        raise NotFoundError(
            "molecule not found", detail=", ".join(sorted(missing_molecules))
        )

    written: list[AssignAttributionOutput] = []
    for decision in request.decisions:
        attribution_id = await asyncio.to_thread(
            repositories.measurements.bind_attribution,
            measurement_id=decision.measurement_id,
            mol_id=decision.mol_id,
            doc_id=request.doc_id,
            evidence_id=decision.evidence_id,
            method="agent",
            confidence=decision.confidence,
        )
        written.append(
            AssignAttributionOutput(
                attribution_id=attribution_id,
                doc_id=request.doc_id,
                short_id=short_doc_id(request.doc_id),
                measurement_id=decision.measurement_id,
                mol_id=decision.mol_id,
                method="agent",
                confidence=decision.confidence,
                evidence_id=decision.evidence_id,
                review_status="accepted",
            )
        )
    return CapabilityResult(
        data=AssignAttributionsOutput(
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id),
            written=written,
            count=len(written),
        )
    )


register(
    Capability(
        name="assign_attributions",
        description=(
            "Write a batch of agent structure-activity adjudications: every "
            "reading -> structure link is validated first (the reading must "
            "exist in the document, the structure must be a stored molecule) and "
            "the whole batch is rejected if one decision cannot be verified. "
            "Each link is written with method=agent; a human link outranks it."
        ),
        input_model=AssignAttributionsInput,
        output_model=AssignAttributionsOutput,
        mutating=True,
        handler=assign_attributions,
    )
)

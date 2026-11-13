"""Binding candidates — the read-only capability for structure-activity decisions.

Where ``verify_structures`` reports what a structure is and ``query_activities``
reports what a reading printed, this capability joins the two around the
designation that connects them: for every designation the document prints, the
structures that claim it and the evidence a reader needs to choose. It decides
nothing, so the agent can compare the rules' resolution against the document.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from mbforge.foundation.errors import NotFoundError
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    doc_id_field,
    register,
)
from mbforge.service.use_cases.documents.binding_candidates import binding_candidates
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.documents.reading_explanation import (
    explain_reading as explain_one,
)


class GetBindingCandidatesInput(BaseModel):
    doc_id: str = doc_id_field()
    offset: int = Field(0, ge=0, description="Number of designations to skip.")
    limit: int = Field(50, ge=1, le=200, description="Maximum designations to return.")


class ReadingRef(BaseModel):
    """One printed reading, compact: what it printed and whether it is owned."""

    measurement_id: str = ""
    label_key: str = ""
    label_raw: str = ""
    reference_type: str = ""
    metric: str = ""
    value: float | None = None
    unit: str = ""
    operator: str = ""
    qualitative: str = ""
    page: int | None = None
    table_idx: int | None = None
    row_idx: int | None = None
    attributed: bool = False
    mol_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class EntryRef(BaseModel):
    entry_id: str = ""
    label_raw: str = ""
    label_key: str = ""
    entry_role: str = ""
    structure_status: str = ""
    review_status: str = ""
    entity_id: str | None = None


class StructureCandidate(BaseModel):
    """One structure that claims a designation, with the evidence to check it."""

    mol_id: str = ""
    smiles: str = ""
    name: str = ""
    labels: list[str] = Field(default_factory=list)
    label_keys: list[str] = Field(default_factory=list)
    #: Where each printed designation came from: ``page_text`` outranks ``crop``.
    label_sources: list[str] = Field(default_factory=list)
    #: How many of this structure's drawings carry each designation.
    designation_counts: dict[str, int] = Field(default_factory=dict)
    #: Whether this designation is the one most of the drawings carry; a
    #: minority or tied printing establishes nothing.
    owns: bool = False
    page: int | None = None
    bbox: list[float] | None = None
    detection_score: float = 0.0
    structure_kind: str = "concrete"
    formula: str = ""
    exact_mass: float | None = None
    mass_check: str = "no_printed_mass"
    entry: EntryRef | None = None


class StructureRef(BaseModel):
    """A drawing no designation has claimed: the material a reading is judged against."""

    mol_id: str = ""
    smiles: str = ""
    name: str = ""
    page: int | None = None
    bbox: list[float] | None = None
    detection_score: float = 0.0
    structure_kind: str = "concrete"
    formula: str = ""
    exact_mass: float | None = None
    printed_ms: list[dict[str, object]] = Field(default_factory=list)
    mass_check: str = "no_printed_mass"


class AttributionRef(BaseModel):
    """The reading's current structure link, reduced to what decides precedence."""

    mol_id: str = ""
    method: str = ""
    confidence: float | None = None
    review_status: str = ""


class DesignationBinding(BaseModel):
    """One designation and the structures that answer to it."""

    label_key: str
    label_raw: str = ""
    reference_types: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    context_types: list[str] = Field(default_factory=list)
    reading_ids: list[str] = Field(default_factory=list)
    #: Whether a printed reading needs this designation placed; a designation
    #: no reading references is context the document printed.
    has_reading: bool = False
    candidates: list[StructureCandidate] = Field(default_factory=list)
    #: Unlabelled drawings printed on this designation's reading pages: what a
    #: ``label_not_read`` decision compares the reading against.
    nearby_structures: list[StructureRef] = Field(default_factory=list)
    attribution: AttributionRef | None = None


class TableCell(BaseModel):
    """A ``[MOL:n]`` placeholder printed in a table cell."""

    page: int | None = None
    evidence_id: str = ""
    tokens: list[str] = Field(default_factory=list)


class ReviewItemRef(BaseModel):
    item_id: str = ""
    kind: str = ""
    page: int | None = None
    name: str | None = None
    smiles: str | None = None
    status: str = "pending"
    reasons: list[str] = Field(default_factory=list)


class BindingSummary(BaseModel):
    readings: int = 0
    attributed_readings: int = 0
    unattributed_readings: int = 0
    designations: int = 0
    candidate_structures: int = 0
    unlabeled_structures: int = 0
    review_items: int = 0
    table_cells: int = 0
    names: int = 0


class GetBindingCandidatesOutput(BaseModel):
    doc_id: str
    short_id: str
    summary: BindingSummary
    designations: list[DesignationBinding]
    readings: list[ReadingRef]
    unlabeled_structures: list[StructureRef] = Field(default_factory=list)
    review_items: list[ReviewItemRef]
    table_cells: list[TableCell]
    names: list[str]
    total: int


def _entry_ref(entry: dict | None) -> EntryRef | None:
    if not entry:
        return None
    return EntryRef(
        entry_id=str(entry.get("entry_id") or ""),
        label_raw=str(entry.get("label_raw") or ""),
        label_key=str(entry.get("label_key") or ""),
        entry_role=str(entry.get("entry_role") or ""),
        structure_status=str(entry.get("structure_status") or ""),
        review_status=str(entry.get("review_status") or ""),
        entity_id=entry.get("entity_id"),
    )


def _review_item(item: dict[str, object]) -> ReviewItemRef:
    page = item.get("page")
    name = item.get("name")
    smiles = item.get("smiles")
    reasons = item.get("reasons")
    return ReviewItemRef(
        item_id=str(item.get("id") or item.get("item_id") or ""),
        kind=str(item.get("kind") or ""),
        page=page if isinstance(page, int) else None,
        name=str(name) if name else None,
        smiles=str(smiles) if smiles else None,
        status=str(item.get("status") or "pending"),
        reasons=[str(reason) for reason in reasons]
        if isinstance(reasons, list)
        else [],
    )


def _candidate(row: dict[str, object]) -> StructureCandidate:
    bbox = row.get("bbox")
    mass = row.get("exact_mass")
    score = row.get("detection_score")
    return StructureCandidate(
        mol_id=str(row.get("mol_id") or ""),
        smiles=str(row.get("smiles") or ""),
        name=str(row.get("name") or ""),
        labels=[str(item) for item in row.get("labels") or []],
        label_keys=[str(item) for item in row.get("label_keys") or []],
        label_sources=[str(item) for item in row.get("label_sources") or []],
        designation_counts={
            str(key): int(value)
            for key, value in (row.get("designation_counts") or {}).items()
        },
        owns=bool(row.get("owns")),
        page=row.get("page") if isinstance(row.get("page"), int) else None,
        bbox=[float(value) for value in bbox] if isinstance(bbox, list) else None,
        detection_score=float(score) if isinstance(score, (int, float)) else 0.0,
        structure_kind=str(row.get("structure_kind") or "concrete"),
        formula=str(row.get("formula") or ""),
        exact_mass=float(mass) if isinstance(mass, (int, float)) else None,
        mass_check=str(row.get("mass_check") or "no_printed_mass"),
        entry=_entry_ref(
            row.get("entry") if isinstance(row.get("entry"), dict) else None
        ),
    )


def _structure_ref(row: dict[str, object]) -> StructureRef:
    bbox = row.get("bbox")
    mass = row.get("exact_mass")
    score = row.get("detection_score")
    return StructureRef(
        mol_id=str(row.get("mol_id") or ""),
        smiles=str(row.get("smiles") or ""),
        name=str(row.get("name") or ""),
        page=row.get("page") if isinstance(row.get("page"), int) else None,
        bbox=[float(value) for value in bbox] if isinstance(bbox, list) else None,
        detection_score=float(score) if isinstance(score, (int, float)) else 0.0,
        structure_kind=str(row.get("structure_kind") or "concrete"),
        formula=str(row.get("formula") or ""),
        exact_mass=float(mass) if isinstance(mass, (int, float)) else None,
        printed_ms=[
            dict(item) for item in row.get("printed_ms") or [] if isinstance(item, dict)
        ],
        mass_check=str(row.get("mass_check") or "no_printed_mass"),
    )


async def get_binding_candidates(
    context: CapabilityContext, request: GetBindingCandidatesInput
) -> CapabilityResult:
    """Report the candidate material for one document's binding decisions."""
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)

    report = await asyncio.to_thread(
        binding_candidates,
        context.library_root,
        request.doc_id,
        offset=request.offset,
        limit=request.limit,
    )
    rows = report["designations"]
    next_offset = (
        request.offset + len(rows)
        if request.offset + len(rows) < report["total"]
        else None
    )
    designations: list[DesignationBinding] = []
    for item in rows:
        attribution = item.get("attribution")
        designations.append(
            DesignationBinding(
                label_key=str(item["label_key"]),
                label_raw=str(item.get("label_raw") or ""),
                reference_types=[
                    str(value) for value in item.get("reference_types") or []
                ],
                pages=[
                    int(value) for value in item.get("pages") or [] if value is not None
                ],
                context_types=[str(value) for value in item.get("context_types") or []],
                reading_ids=[str(value) for value in item.get("reading_ids") or []],
                has_reading=bool(item.get("has_reading")),
                candidates=[_candidate(row) for row in item.get("candidates") or []],
                nearby_structures=[
                    _structure_ref(row) for row in item.get("nearby_structures") or []
                ],
                attribution=(
                    AttributionRef(
                        mol_id=str(attribution.get("mol_id") or ""),
                        method=str(attribution.get("method") or ""),
                        confidence=(
                            float(attribution["confidence"])
                            if isinstance(attribution.get("confidence"), (int, float))
                            else None
                        ),
                        review_status=str(attribution.get("review_status") or ""),
                    )
                    if attribution
                    else None
                ),
            )
        )

    return CapabilityResult(
        data=GetBindingCandidatesOutput(
            doc_id=report["doc_id"],
            short_id=short_doc_id(report["doc_id"]),
            summary=BindingSummary(**report["summary"]),
            designations=designations,
            readings=[ReadingRef(**row) for row in report["readings"]],
            unlabeled_structures=[
                _structure_ref(row) for row in report["unlabeled_structures"]
            ],
            review_items=[_review_item(item) for item in report["review_items"]],
            table_cells=[TableCell(**row) for row in report["table_cells"]],
            names=list(report["names"]),
            total=report["total"],
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


register(
    Capability(
        name="get_binding_candidates",
        description=(
            "Candidate material for structure-activity binding decisions on one "
            "document. For every designation the document prints — in a "
            "reading, on a drawing, or in a compound entry — it reports the "
            "structures that claim it, with the evidence to choose: printed "
            "labels and where they came from (page text vs crop), how many "
            "drawings carry each designation, page/bbox, detection score, "
            "formula and exact mass, the printed-mass verdict, the owning "
            "compound entry and the reading's current attribution. Also "
            "returns the readings, the pending review items and the table-cell "
            "molecule tokens. Read-only and deterministic: it decides nothing "
            "and writes nothing. Use inspect_visual to look at a page before "
            "choosing."
        ),
        input_model=GetBindingCandidatesInput,
        output_model=GetBindingCandidatesOutput,
        mutating=False,
        handler=get_binding_candidates,
    )
)


class ExplainReadingInput(BaseModel):
    doc_id: str = doc_id_field()
    measurement_id: str = Field(
        min_length=1,
        max_length=128,
        description="The reading to explain, as query_activities reports it.",
    )


class ExplainReadingOutput(BaseModel):
    """The chain from a printed reading to the structure that should own it."""

    model_config = ConfigDict(extra="allow")

    doc_id: str
    measurement_id: str
    found: bool = True
    printed: dict[str, object] = Field(default_factory=dict)
    reference_space: dict[str, object] = Field(default_factory=dict)
    drawings: dict[str, object] = Field(default_factory=dict)
    entry_side: list[object] = Field(default_factory=list)
    verdict: dict[str, object] = Field(default_factory=dict)
    next_step: str = ""


async def explain_reading(
    context: CapabilityContext, request: ExplainReadingInput
) -> CapabilityResult:
    """Report every link between one reading and the structure that should own it."""
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)
    report = await asyncio.to_thread(
        explain_one,
        context.library_root,
        request.doc_id,
        request.measurement_id,
    )
    return CapabilityResult(data=ExplainReadingOutput(**report))


register(
    Capability(
        name="explain_reading",
        description=(
            "Why one reading has no structure, in one read: what the document "
            "printed, which reference space it printed it in (compound vs "
            "example), the drawings that carry that designation, the compound "
            "entries involved, the reason the dataset reports with its inputs, "
            "and the next step that follows from it. Read-only; it decides "
            "nothing. Use it before changing a rule or re-extracting."
        ),
        input_model=ExplainReadingInput,
        output_model=ExplainReadingOutput,
        mutating=False,
        handler=explain_reading,
    )
)

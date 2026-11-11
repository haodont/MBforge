"""Read-only Patent facts and measurement capabilities exposed to agents.

Split from ``capabilities.read`` by responsibility.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from mbforge.contracts.measurement import MeasurementDatasetStats
from mbforge.contracts.patent import AnalysisStatus, ExtractionMode
from mbforge.foundation.errors import NotFoundError
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    doc_id_field,
    register,
)
from mbforge.service.dto.activity import ActivityRecordResponse
from mbforge.service.use_cases.documents.activity_queries import (
    dataset_stats,
    list_activity_records,
)
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.documents.patent_facts import load_patent_facts

if TYPE_CHECKING:
    from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact


PatentCollection = Literal[
    "summary",
    "sections",
    "entries",
    "issues",
    "synthesis_steps",
    "names",
    "characterizations",
    "assay_methods",
    "examples",
    "structure_activity",
    "conflicts",
    "review_candidates",
]


class GetPatentResultInput(BaseModel):
    doc_id: str = doc_id_field()
    collection: PatentCollection = Field(
        "summary",
        description=(
            "Facts collection to return; summary carries counts/stats and no items."
        ),
    )
    offset: int = Field(0, ge=0, description="Number of collection rows to skip.")
    limit: int = Field(
        20, ge=1, le=100, description="Maximum collection rows to return."
    )
    include_evidence_ids: bool = Field(
        False,
        description="Include evidence_ids on returned fact rows when available.",
    )


class PatentFactCounts(BaseModel):
    sections: int
    entries: int
    synthesis_steps: int
    assay_methods: int
    examples: int
    measurements: int
    issues: int


class GetPatentResultOutput(BaseModel):
    """One Patent facts collection, plus the document summary.

    ``collection`` is echoed in the response and only the requested
    collection is returned: ``summary`` carries ``counts``/``stats`` and an
    empty ``items``, every other collection carries ``items`` with
    ``counts``/``stats`` cleared. ``total`` is the unpaginated size of the
    selected collection. ``evidence_ids`` is omitted from every item unless
    ``include_evidence_ids`` is set.
    """

    doc_id: str
    short_id: str
    run_id: str
    revision: int
    projection_status: Literal["current", "pending", "legacy"] | None = None
    collection: PatentCollection
    total: int = 0
    items: list[dict[str, Any]] = Field(default_factory=list)
    counts: PatentFactCounts | None = None
    stats: dict[str, Any] | None = None
    analysis_status: AnalysisStatus | None = None
    extraction_mode: ExtractionMode | None = None


class QueryActivitiesInput(BaseModel):
    doc_id: str = doc_id_field()
    metric: str = Field(
        "", max_length=64, description="Activity metric, for example IC50."
    )
    target: str = Field(
        "", max_length=128, description="Biological target or cell line."
    )
    assay_description: str = Field(
        "", max_length=256, description="Assay description substring."
    )
    min_value: float | None = Field(
        None, description="Minimum canonical value included in the result."
    )
    max_value: float | None = Field(
        None, description="Maximum canonical value included in the result."
    )
    offset: int = Field(0, ge=0, description="Number of readings to skip.")
    limit: int = Field(
        200, ge=1, le=500, description="Maximum activity readings to return."
    )


class QueryActivitiesOutput(BaseModel):
    doc_id: str
    short_id: str
    stats: MeasurementDatasetStats
    items: list[ActivityRecordResponse]


_EVIDENCE_REF_FIELDS = frozenset({"evidence_ids", "evidence"})


def _facts_collection(
    facts: PatentFactsArtifact, collection: str
) -> list[dict[str, Any]]:
    """One selected facts collection as rows; ``summary`` selects none."""
    if collection == "summary":
        return []
    if collection == "sections":
        return [section.model_dump() for section in facts.sections]
    return list(getattr(facts, collection))


def _omit_evidence_refs(row: dict[str, Any]) -> dict[str, Any]:
    """Drop an evidence-id array, which otherwise dominates the payload."""
    return {
        key: value
        for key, value in row.items()
        if key not in _EVIDENCE_REF_FIELDS
        or not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        )
    }


async def get_patent_result(
    context: CapabilityContext, request: GetPatentResultInput
) -> CapabilityResult:
    facts = await asyncio.to_thread(
        load_patent_facts, context.library_root, request.doc_id
    )
    if facts is None:
        raise NotFoundError("patent facts not available", detail=request.doc_id)

    rows = _facts_collection(facts, request.collection)
    if not request.include_evidence_ids:
        rows = [_omit_evidence_refs(row) for row in rows]
    next_offset = (
        request.offset + request.limit
        if request.offset + request.limit < len(rows)
        else None
    )
    summary = request.collection == "summary"
    counts = (
        PatentFactCounts(
            sections=len(facts.sections),
            entries=len(facts.entries),
            synthesis_steps=len(facts.synthesis_steps),
            assay_methods=len(facts.assay_methods),
            examples=len(facts.examples),
            measurements=len(facts.measurements),
            issues=len(facts.issues),
        )
        if summary
        else None
    )
    return CapabilityResult(
        data=GetPatentResultOutput(
            doc_id=facts.doc_id,
            short_id=short_doc_id(facts.doc_id),
            run_id=facts.run_id,
            revision=facts.revision,
            projection_status=facts.projection_status,
            collection=request.collection,
            total=len(rows),
            items=rows[request.offset : request.offset + request.limit],
            counts=counts,
            stats=facts.stats if summary else None,
            analysis_status=facts.analysis_status if summary else None,
            extraction_mode=facts.extraction_mode if summary else None,
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def query_activities(
    context: CapabilityContext, request: QueryActivitiesInput
) -> CapabilityResult:
    """Return every printed activity reading for one document.

    This is the canonical structured-activity surface: it reads the SQL
    ``measurements`` rows and their attributions, not the Patent facts counts
    or a text search. The page is stable and every reading is returned, with
    ``attributed``/``mol_ids`` distinguishing a named molecule from an orphan.
    """
    records = await asyncio.to_thread(
        list_activity_records,
        context.library_root,
        request.doc_id,
        request.target,
        request.assay_description,
        request.limit + 1,
        metric=request.metric,
        min_value=request.min_value,
        max_value=request.max_value,
        offset=request.offset,
    )
    truncated = len(records) > request.limit
    page = records[: request.limit]
    stats = await asyncio.to_thread(dataset_stats, context.library_root, request.doc_id)
    return CapabilityResult(
        data=QueryActivitiesOutput(
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id),
            stats=stats,
            items=page,
        ),
        truncated=truncated,
        next_offset=request.offset + request.limit if truncated else None,
    )


register(
    Capability(
        name="get_patent_result",
        description=(
            "Read one Patent facts collection, paged. Default collection=summary "
            "returns counts, stats and the run identity only — no sections and no "
            "entries. Pick exactly one of sections/entries/issues/synthesis_steps/"
            "names/characterizations/assay_methods/examples/structure_activity/"
            "conflicts/review_candidates; offset/limit page that collection and "
            "total is its unpaginated size. evidence_ids arrays are omitted unless "
            "include_evidence_ids is true. Contains no measurement values; use "
            "query_activities for activity readings."
        ),
        input_model=GetPatentResultInput,
        output_model=GetPatentResultOutput,
        mutating=False,
        handler=get_patent_result,
    )
)


register(
    Capability(
        name="query_activities",
        description=(
            "Canonical reading-level activity dataset for one document. Returns "
            "every stored measurement, including readings no structure owns, with "
            "assay, value, page, evidence ids and attributed molecule identities. "
            "No activity threshold is applied; follow next_offset before claiming "
            "completeness. Do not reconstruct this dataset from get_patent_result "
            "counts, Markdown, or search_evidence."
        ),
        input_model=QueryActivitiesInput,
        output_model=QueryActivitiesOutput,
        mutating=False,
        handler=query_activities,
    )
)

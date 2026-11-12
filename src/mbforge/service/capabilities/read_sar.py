"""Read-only SAR series capability: molecules joined to their activities.

Assembles a congeneric series in one structured page so the agent can reason
over structure -> activity without correlating ``search_molecules`` and
``query_activities`` by id. Each molecule carries its attributed readings, the
evidence ids and page behind every value, and the review state of the molecule,
the reading and the structure link.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from mbforge.service.capabilities.registry import (
    DOC_ID_DESCRIPTION,
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.molecule.series import analyze_series


class AnalyzeSeriesInput(BaseModel):
    doc_id: str = Field("", max_length=128, description=DOC_ID_DESCRIPTION)
    query: str = Field(
        "",
        max_length=512,
        description=(
            "Optional SMILES/SMARTS or text selecting the series members; "
            "mode=auto takes the substructure path for a parseable structure. "
            "Empty with doc_id set returns that document's molecules."
        ),
    )
    mode: Literal["auto", "text", "substructure", "similarity"] = Field(
        "auto", description="Search path when query is set."
    )
    similarity_threshold: float = Field(
        0.5, ge=0.0, le=1.0, description="Minimum Tanimoto for similarity mode."
    )
    metric: str = Field(
        "", max_length=64, description="Keep only readings of this metric (e.g. IC50)."
    )
    target: str = Field(
        "",
        max_length=128,
        description="Keep only readings whose target contains this text.",
    )
    offset: int = Field(0, ge=0, description="Number of series molecules to skip.")
    limit: int = Field(
        20, ge=1, le=50, description="Maximum series molecules to return."
    )

    @model_validator(mode="after")
    def _require_scope(self) -> AnalyzeSeriesInput:
        if not self.doc_id and not self.query:
            raise ValueError("provide doc_id or query to scope the series")
        return self


class SeriesActivity(BaseModel):
    """One reading attributed to a series molecule, with its evidence and link."""

    measurement_id: str
    metric: str = ""
    target: str = ""
    species: str = ""
    assay_type: str = ""
    assay_description: str = ""
    value_canonical: float | None = None
    unit_canonical: str = ""
    value_original: float | None = None
    unit_original: str = ""
    operator: str = ""
    value_text: str = ""
    page_num: int | None = None
    table_idx: int | None = None
    row_idx: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_grade: str = ""
    review_status: str = "pending"
    attribution_method: str = ""
    attribution_confidence: float | None = None
    attribution_review_status: str = ""


class SeriesMolecule(BaseModel):
    """One series member: a structure plus its attributed activity readings."""

    mol_id: str
    canonical_smiles: str
    esmiles: str = ""
    name: str = ""
    review_status: str = "pending"
    structure_role: str = ""
    source_doc: str | None = None
    short_id: str = ""
    similarity: float | None = None
    activities: list[SeriesActivity] = Field(default_factory=list)


class AnalyzeSeriesOutput(BaseModel):
    doc_id: str = ""
    short_id: str = ""
    query: str = ""
    requested_mode: Literal["auto", "text", "substructure", "similarity"] = "auto"
    resolved_mode: str = ""
    items: list[SeriesMolecule] = Field(default_factory=list)


async def analyze_series_capability(
    context: CapabilityContext, request: AnalyzeSeriesInput
) -> CapabilityResult:
    result = await asyncio.to_thread(
        analyze_series,
        context.library_root,
        doc_id=request.doc_id,
        query=request.query,
        mode=request.mode,
        similarity_threshold=request.similarity_threshold,
        metric=request.metric,
        target=request.target,
        offset=request.offset,
        limit=request.limit,
    )
    items = [
        SeriesMolecule(
            **{
                **molecule,
                "short_id": short_doc_id(molecule["source_doc"])
                if molecule["source_doc"]
                else "",
            }
        )
        for molecule in result["items"]
    ]
    return CapabilityResult(
        data=AnalyzeSeriesOutput(
            doc_id=request.doc_id,
            short_id=short_doc_id(request.doc_id) if request.doc_id else "",
            query=request.query,
            requested_mode=request.mode,
            resolved_mode=result["resolved_mode"],
            items=items,
        ),
        truncated=result["truncated"],
        next_offset=result["next_offset"],
    )


register(
    Capability(
        name="analyze_series",
        description=(
            "Assemble a structure-activity (SAR) series: each matching molecule "
            "joined to its attributed activity readings, the evidence ids and "
            "page behind every value, and the review state of the molecule, the "
            "reading and the structure link. Scope by doc_id (a document's "
            "molecules) and/or query (a SMILES substructure or similarity search "
            "across the library). A member with no measured activity is kept "
            "with an empty activities list; readings no structure owns are "
            "excluded. Use this for SAR instead of correlating search_molecules "
            "and query_activities by id. Paginates over molecules."
        ),
        input_model=AnalyzeSeriesInput,
        output_model=AnalyzeSeriesOutput,
        mutating=False,
        handler=analyze_series_capability,
    )
)

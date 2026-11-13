"""Read-only SAR series capability: molecules joined to their activities.

Assembles a congeneric series in one structured page so the agent can reason
over structure -> activity without correlating ``search_molecules`` and
``query_activities`` by id. Each molecule carries its attributed readings, the
evidence ids and page behind every value, and the review state of the molecule,
the reading and the structure link.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
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
    format: Literal["json", "markdown"] = Field(
        "json",
        description=(
            "`json` (default) returns the structured rows. `markdown` returns the "
            "same rows rendered as one two-source table (value evidence beside "
            "structure evidence), so a reply can quote it instead of retyping "
            "SMILES and evidence ids."
        ),
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
    #: The drawing this SMILES was read from — the structure half of a citation,
    #: beside the reading's ``evidence_ids``. Empty when the molecule has no
    #: structure evidence in the document (for example a name-resolved entry).
    structure_evidence_id: str = ""
    structure_page: int | None = None
    structure_bbox: list[float] | None = None
    #: ``match`` / ``mismatch`` / ``not_comparable`` / ``no_printed_mass``; the
    #: same verdict ``verify_structures`` reports for this structure.
    mass_check: str = ""
    activities: list[SeriesActivity] = Field(default_factory=list)


class AnalyzeSeriesOutput(BaseModel):
    doc_id: str = ""
    short_id: str = ""
    query: str = ""
    requested_mode: Literal["auto", "text", "substructure", "similarity"] = "auto"
    resolved_mode: str = ""
    items: list[SeriesMolecule] = Field(default_factory=list)


class ActivityTableOutput(AnalyzeSeriesOutput):
    """The same series rows rendered as one Markdown table (``format=markdown``).

    It extends the JSON output so the capability keeps one declared output
    model: ``items`` stays empty and the table carries the rows.
    """

    format: Literal["markdown"] = "markdown"
    columns: list[str] = Field(default_factory=list)
    rows: int = 0
    table: str = ""
    #: Molecules that carry no reading for the requested metric. They keep their
    #: row (an empty value is a SAR fact), and are listed so a reply never reads
    #: "no activity" as "no such compound".
    without_reading: list[str] = Field(default_factory=list)
    #: Molecules in scope that were omitted because no reading for the metric is
    #: attributed to them (``format=markdown`` pages over measured compounds).
    unmeasured: int = 0


_TABLE_COLUMNS = [
    "化合物",
    "指标",
    "值",
    "单位",
    "页",
    "SMILES",
    "数值来源",
    "结构来源",
    "质量校验",
]


def _cell(value: object) -> str:
    """One markdown cell: a pipe would split the row, a newline would end it."""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _citations(evidence_ids: Sequence[str]) -> str:
    return " ".join(
        f"[[ev:{evidence_id}]]" for evidence_id in evidence_ids if evidence_id
    )


def _value_text(activity: SeriesActivity) -> str:
    value = activity.value_canonical
    if value is None:
        return activity.value_text
    operator = activity.operator if activity.operator not in ("", "=") else ""
    return f"{operator}{value:g}"


def _sorted_activities(activities: Sequence[SeriesActivity]) -> list[SeriesActivity]:
    """Group by metric and order by value, so potency reads top-down.

    A reading without a numeric value (a qualitative ``A``/``B`` grade or a
    censored ``>`` threshold) sorts after the measured ones of its metric.
    """
    return sorted(
        activities,
        key=lambda activity: (
            activity.metric or "",
            activity.value_canonical is None,
            activity.value_canonical if activity.value_canonical is not None else 0.0,
        ),
    )


def render_series_table(
    items: Sequence[SeriesMolecule],
) -> tuple[list[str], int, list[str], str]:
    """Render series rows as one two-source Markdown table.

    Returns the columns, the row count, the molecules without a reading, and the
    table text. Every cell comes from the row data: the SMILES is the stored
    canonical string and both evidence columns are the stored ids, so quoting the
    table cannot mis-transcribe either.
    """
    multi_doc = len({item.source_doc for item in items if item.source_doc}) > 1
    columns = (["文档"] if multi_doc else []) + list(_TABLE_COLUMNS)
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "---|" * len(columns),
    ]
    rows = 0
    without_reading: list[str] = []
    #: (sort key, cells) — the table reads top-down by metric then potency, so a
    #: reader compares values in place instead of scanning a molecule-ordered list.
    pending: list[tuple[tuple[str, bool, float, str], list[object]]] = []
    for item in items:
        label = item.name or item.mol_id
        structure = _citations([item.structure_evidence_id])
        doc_cell = [item.short_id] if multi_doc else []
        activities = _sorted_activities(item.activities)
        if not activities:
            without_reading.append(label)
            # An unmeasured molecule sorts last (`~` > any metric name) instead of
            # heading the table with an empty value.
            pending.append(
                (
                    ("~", True, 0.0, label),
                    doc_cell
                    + [
                        label,
                        "",
                        "",
                        "",
                        "",
                        f"`{item.canonical_smiles}`",
                        "",
                        structure,
                        item.mass_check,
                    ],
                )
            )
            continue
        for activity in activities:
            page = (
                activity.page_num
                if activity.page_num is not None
                else item.structure_page
            )
            value = activity.value_canonical
            pending.append(
                (
                    (
                        activity.metric or "~",
                        value is None,
                        value if value is not None else 0.0,
                        label,
                    ),
                    doc_cell
                    + [
                        label,
                        activity.metric,
                        _value_text(activity),
                        activity.unit_canonical or activity.unit_original,
                        page,
                        f"`{item.canonical_smiles}`",
                        _citations(activity.evidence_ids),
                        structure,
                        item.mass_check,
                    ],
                )
            )
    for _, cells in sorted(pending, key=lambda entry: entry[0]):
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
        rows += 1
    return columns, rows, without_reading, "\n".join(lines)


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
        measured_only=request.format == "markdown",
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
    if request.format == "markdown":
        columns, rows, without_reading, table = render_series_table(items)
        return CapabilityResult(
            data=ActivityTableOutput(
                doc_id=request.doc_id,
                short_id=short_doc_id(request.doc_id) if request.doc_id else "",
                columns=columns,
                rows=rows,
                table=table,
                without_reading=without_reading,
                unmeasured=result.get("unmeasured", 0),
            ),
            truncated=result["truncated"],
            next_offset=result["next_offset"],
        )
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
            "and query_activities by id. Paginates over molecules. "
            "`format=markdown` returns `{table, columns, rows, without_reading}` "
            "instead of `items`: one row per reading with the value evidence and "
            "the structure evidence side by side, so a reply quotes the table "
            "instead of retyping SMILES and ids. A molecule without a reading for "
            "the requested metric keeps an empty-value row and is named in "
            "`without_reading`."
        ),
        input_model=AnalyzeSeriesInput,
        output_model=AnalyzeSeriesOutput,
        mutating=False,
        handler=analyze_series_capability,
    )
)

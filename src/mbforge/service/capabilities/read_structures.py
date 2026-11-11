"""Structure verification — the read-only capability for checking structures.

Split from ``capabilities.read`` by responsibility: this file owns the one
capability that reports a document's structures with the chemistry a reader
needs to check them (formula, masses, printed designation, owning compound
entry, printed mass delta).
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
from mbforge.service.use_cases.documents.structure_verification import (
    verify_structures as verify_structures_use_case,
)


class VerifyStructuresInput(BaseModel):
    doc_id: str = doc_id_field()
    page: int | None = Field(None, ge=1)
    label: str | None = Field(None, max_length=64)
    offset: int = Field(0, ge=0)
    limit: int = Field(25, ge=1, le=100)


class PrintedMassCheck(BaseModel):
    printed_mz: float
    adduct: str
    expected_mz: float
    delta: float
    tolerance: float
    verdict: Literal["match", "mismatch", "not_comparable"]
    label_key: str
    page: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    raw_text: str = ""


class CompoundEntryRef(BaseModel):
    entry_id: str
    label_raw: str = ""
    label_key: str = ""
    entry_role: str = ""
    structure_status: str = ""
    review_status: str = ""
    entity_id: str | None = None


class VerifiedStructure(BaseModel):
    page: int | None = None
    evidence_id: str | None = None
    mol_id: str = ""
    smiles: str = ""
    esmiles: str = ""
    canonical_smiles: str = ""
    formula: str = ""
    main_formula: str = ""
    molar_mass: float | None = None
    exact_mass: float | None = None
    mass_basis: str = "largest_fragment"
    detection_score: float = 0.0
    structure_kind: Literal["concrete", "markush"] = "concrete"
    bbox: list[float] | None = None
    printed_labels: list[str] = Field(default_factory=list)
    label_keys: list[str] = Field(default_factory=list)
    entry: CompoundEntryRef | None = None
    printed_ms: list[PrintedMassCheck] = Field(default_factory=list)
    mass_check: Literal["match", "mismatch", "not_comparable", "no_printed_mass"] = (
        "no_printed_mass"
    )


class VerificationSummary(BaseModel):
    structures: int = 0
    structures_with_printed_ms: int = 0
    mass_matches: int = 0
    mass_mismatches: int = 0
    mass_not_comparable: int = 0
    structures_without_printed_ms: int = 0
    printed_ms_lines: int = 0
    printed_ms_unowned: int = 0
    printed_ms_from_structure_rows: int = 0
    printed_ms_source: str = "none"


class VerifyStructuresOutput(BaseModel):
    doc_id: str
    short_id: str
    summary: VerificationSummary
    items: list[VerifiedStructure]


def _entry_ref(entry: dict | None) -> CompoundEntryRef | None:
    """The compound entry that owns a structure's designation."""
    if not entry:
        return None
    return CompoundEntryRef(
        entry_id=str(entry.get("entry_id") or ""),
        label_raw=str(entry.get("label_raw") or ""),
        label_key=str(entry.get("label_key") or ""),
        entry_role=str(entry.get("entry_role") or ""),
        structure_status=str(entry.get("structure_status") or ""),
        review_status=str(entry.get("review_status") or ""),
        entity_id=entry.get("entity_id"),
    )


async def verify_structures(
    context: CapabilityContext, request: VerifyStructuresInput
) -> CapabilityResult:
    """Report every structure of a document with the chemistry to check it.

    One row per recognized structure: its formula and masses, the printed
    designation it carries, the compound entry that owns it, and the printed
    MS line that designation owns with the mass delta. A delta is evidence,
    not a verdict — nothing here writes or corrects a structure.
    """
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)

    report = await asyncio.to_thread(
        verify_structures_use_case,
        context.library_root,
        request.doc_id,
        page=request.page,
        label=request.label,
        offset=request.offset,
        limit=request.limit + 1,
    )
    fetched = report["items"]
    items = fetched[: request.limit]
    next_offset = request.offset + len(items) if len(fetched) > request.limit else None
    return CapabilityResult(
        data=VerifyStructuresOutput(
            doc_id=report["doc_id"],
            short_id=short_doc_id(report["doc_id"]),
            summary=VerificationSummary(**report["summary"]),
            items=[
                VerifiedStructure(
                    **{key: value for key, value in item.items() if key != "entry"},
                    entry=_entry_ref(item.get("entry")),
                )
                for item in items
            ],
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


register(
    Capability(
        name="verify_structures",
        description=(
            "Structure verification for one document. Returns every recognized "
            "structure with its formula, molar mass, monoisotopic mass "
            "(salt-stripped parent), the printed designation it carries, the "
            "compound entry that owns it, and the printed MS line that "
            "designation owns with the mass delta and a match/mismatch verdict "
            "at the patent's own 0.6 Da tolerance. Read-only and deterministic: "
            "a delta is evidence for a human, never a correction. Use "
            "list_evidence for the raw rows and inspect_visual/molecule_image "
            "to look at the drawing."
        ),
        input_model=VerifyStructuresInput,
        output_model=VerifyStructuresOutput,
        mutating=False,
        handler=verify_structures,
    )
)

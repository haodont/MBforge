"""File schema for the Patent facts artifact.

The current Patent artifact is published at
``storage/{doc_id}/patent_facts.json``:

- ``patent_facts.json`` — compound entries + document segments + assay methods
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mbforge.contracts.patent import AnalysisStatus, ExtractionMode


class PatentSectionModel(BaseModel):
    """A segmented example/preparation section of the document."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str
    kind: str  # one of patent.sections.SECTION_KINDS
    page_start: int
    page_end: int
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceReadCoverage(BaseModel):
    """Tool-return coverage; never a claim of semantic verification."""

    model_config = ConfigDict(extra="forbid")

    total_evidence: int = Field(ge=0)
    complete_evidence: int = Field(ge=0)
    partial_evidence: int = Field(ge=0)
    complete_pages: list[int]
    partial_pages: list[int]
    unread_pages: list[int]
    no_evidence_pages: list[int]


class PatentFactsArtifact(BaseModel):
    """``patent_facts.json`` — entries survive even when structure
    recognition fails."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    run_id: str
    revision: int = 0
    """Committed snapshot revision this projection was written for (0 = legacy)."""
    projection_status: Literal["current", "pending", "legacy"] | None = None
    """Read-time observation, excluded from SQL and the file projection."""
    coverage: EvidenceReadCoverage | None = None
    sections: list[PatentSectionModel] = Field(default_factory=list)
    entries: list[dict[str, Any]] = Field(default_factory=list)
    """CompoundEntry dicts (mbforge.domain.patent.CompoundEntry.to_dict())."""
    synthesis_steps: list[dict[str, Any]] = Field(default_factory=list)
    """Preparation routes: route_id/label_key/product_label/steps/yield_raw,
    each step verbatim with the evidence ids it was printed on. Produced by the
    deterministic pass (``extract_synthesis_routes``), never by the model."""
    names: list[dict[str, Any]] = Field(default_factory=list)
    """Chemistry names printed for a designation (label_key/name_raw/evidence).
    Verbatim; a name is recorded, never derived from a structure."""
    characterizations: list[dict[str, Any]] = Field(default_factory=list)
    """Printed spectra and elemental data (technique nmr|ms|elemental, raw_text
    verbatim, label_key when the passage names a designation). ``attribution``
    says whether that link resolved; the unresolved residue is a gap, not a guess."""
    assay_methods: list[dict[str, Any]] = Field(default_factory=list)
    """AssayMethod dicts (mbforge.domain.activity.AssayMethod.to_dict())."""
    examples: list[dict[str, Any]] = Field(default_factory=list)
    """Example facts projected into the unified Patent artifact."""
    measurements: list[dict[str, Any]] = Field(default_factory=list)
    """ActivityMeasurement dicts
    (mbforge.domain.activity.ActivityMeasurement.to_dict());
    unlinked measurements are preserved here, never faked into the DB."""
    structure_activity: list[dict[str, Any]] = Field(default_factory=list)
    """Readings joined to the structure their example heading declares.

    Each pair is ``{declared_key, measurement_id, smiles, metric, value, unit,
    verified_by_mass, printed_mz, calculated_mz}``. The join key is the
    designation the document prints in its own heading
    (``实施例1: <name>(化合物1)``), not a label recovered from beside a drawing, so
    the join does not depend on label detection succeeding.

    ``verified_by_mass`` records whether the example's printed product mass
    agrees with calculated [M+H]+ within tolerance. It is a consistency flag,
    not proof of structure identity; mass alone never creates a pair."""
    issues: list[dict[str, Any]] = Field(default_factory=list)
    """Review issues: code/message/severity/evidence_ids/related_fact_id."""
    analysis_status: AnalysisStatus = "disabled"
    """disabled | succeeded | fallback — how the LLM pass ended for this run."""
    extraction_mode: ExtractionMode = "deterministic"
    """deterministic | hybrid — hybrid means the valid set merged LLM readings."""
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    """PatentConflict dumps: one per contested slot; neither reading is adopted."""
    review_candidates: list[dict[str, Any]] = Field(default_factory=list)
    """Candidates awaiting review; never part of the valid ``measurements``."""
    llm: dict[str, Any] = Field(default_factory=dict)
    """Run metadata: turns, tool calls, tokens (null when unreported), errors."""
    stats: dict[str, Any] = Field(default_factory=dict)
    """Parse result and review counts only, not progress or raw text."""

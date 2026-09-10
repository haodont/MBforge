"""File schema for the Patent facts artifact.

The current Patent artifact is published at
``storage/{doc_id}/patent_facts.json``:

- ``patent_facts.json`` — compound entries + document segments + assay methods
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PatentSectionModel(BaseModel):
    """A segmented example/preparation section of the document."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str
    kind: str  # example / preparation / comparison / reference
    page_start: int
    page_end: int
    evidence_ids: list[str] = Field(default_factory=list)


class PatentFactsArtifact(BaseModel):
    """``patent_facts.json`` — entries survive even when structure
    recognition fails (spec §8 M1 acceptance)."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    run_id: str
    sections: list[PatentSectionModel] = Field(default_factory=list)
    entries: list[dict[str, Any]] = Field(default_factory=list)
    """CompoundEntry dicts (core.patent.CompoundEntry.to_dict())."""
    synthesis_steps: list[dict[str, Any]] = Field(default_factory=list)
    """SynthesisStep dicts (core.synthesis.SynthesisStep.to_dict());
    rule-extracted by PatentStage (spec §5 decision 1: no LLM)."""
    assay_methods: list[dict[str, Any]] = Field(default_factory=list)
    """AssayMethod dicts (core.activity.AssayMethod.to_dict())."""
    examples: list[dict[str, Any]] = Field(default_factory=list)
    """Example facts projected into the unified Patent artifact."""
    measurements: list[dict[str, Any]] = Field(default_factory=list)
    """ActivityMeasurement dicts (core.activity.ActivityMeasurement.to_dict());
    unlinked measurements are preserved here, never faked into the DB."""
    issues: list[dict[str, Any]] = Field(default_factory=list)
    """Review issues: code/message/severity/evidence_ids/related_fact_id."""
    stats: dict[str, Any] = Field(default_factory=dict)
    """Parse result and review counts only, not progress or raw text."""

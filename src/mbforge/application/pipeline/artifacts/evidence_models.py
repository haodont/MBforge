"""Strict DTOs for the page-evidence fork/join boundary.

The Extract and Detection stages write independent run-scoped branch files;
Join validates both branches and writes the canonical source-evidence facts
to SQLite. These models define the branch file schemas and the in-memory
joined evidence batch.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mbforge.domain.evidence import SourceEvidence

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)


class _EvidenceArtifactModel(BaseModel):
    """Strict models for the page-evidence fork/join boundary."""

    model_config = ConfigDict(extra="forbid")


class PageFrame(_EvidenceArtifactModel):
    """One visual PDF page frame shared by both producer branches."""

    page: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: int = 0


class ExtractPage(_EvidenceArtifactModel):
    """One page of raw Extract output."""

    page_num: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: int = 0
    text: str = ""
    ocr_dpi: int = 0
    text_spans: list[dict[str, JsonValue]] = Field(default_factory=list)
    figure_bboxes: list[list[float]] = Field(default_factory=list)
    # Typed layout regions from the local detector, carrying the producer's own
    # ``kind`` label (``chem`` / ``figcx`` / ``eqn`` …) alongside the geometric
    # bbox and any recognized text. Empty for the cloud-OCR layout path, which
    # only yields the three-value ``block_type``.
    regions: list[dict[str, JsonValue]] = Field(default_factory=list)
    ocr_backend: str | None = None
    ocr_attempts: int = 0
    ocr_elapsed_ms: int = 0
    ocr_error: str | None = None


class DetectionPage(_EvidenceArtifactModel):
    """One page of raw Detection output."""

    page_num: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: int = 0
    detections: list[dict[str, JsonValue]] = Field(default_factory=list)


class CandidateArtifact(_EvidenceArtifactModel):
    """Detection interpretation with candidate fields and evidence IDs."""

    candidate_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: str = "pending"
    smiles: str
    esmiles: str = ""
    markush: bool = False
    groups: str = ""
    refs: list[str] = Field(default_factory=list)
    reject_reason: str | None = None


class ExtractArtifact(_EvidenceArtifactModel):
    """Raw Extract branch output; final evidence IDs do not exist yet."""

    doc_id: str
    run_id: str
    meta: dict[str, JsonValue] = Field(default_factory=dict)
    pages: list[ExtractPage] = Field(default_factory=list)


class DetectionArtifact(_EvidenceArtifactModel):
    """Raw Detection branch output; normalization happens after Join."""

    doc_id: str
    run_id: str
    meta: dict[str, JsonValue] = Field(default_factory=dict)
    pages: list[DetectionPage] = Field(default_factory=list)


class DocumentEvidenceArtifact(_EvidenceArtifactModel):
    """Joined evidence batch passed between stages in memory and tests."""

    doc_id: str
    run_id: str
    conventions: dict[str, str]
    pages: list[PageFrame] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    candidates: list[CandidateArtifact] = Field(default_factory=list)
    molecule_stats: dict[str, JsonValue] = Field(default_factory=dict)

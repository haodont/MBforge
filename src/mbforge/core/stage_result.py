"""Stage result contract (canonical home).

Every pipeline stage returns a ``StageResult``. Errors are categorized by a
machine-readable ``error_code`` and a ``recoverable`` flag so the runner can
decide whether to continue (skip the stage) or abort the whole pipeline, and
so the frontend can show actionable messages.

Lives in core because it is the shared vocabulary between pipeline stages,
the infra executor and the stage registry (:mod:`mbforge.core.stage`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


class PipelineErrorCode:
    """Machine-readable error codes emitted by pipeline stages."""

    PDF_PARSE_ERROR = "PDF_PARSE_ERROR"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    MOLDET_UNAVAILABLE = "MOLDET_UNAVAILABLE"
    MOLPARSER_FAILED = "MOLPARSER_FAILED"
    MOLECULE_NORMALIZATION_FAILED = "MOLECULE_NORMALIZATION_FAILED"
    MOLECULE_TOOL_UNAVAILABLE = "MOLECULE_TOOL_UNAVAILABLE"
    ACTIVITY_EXTRACTION_FAILED = "ACTIVITY_EXTRACTION_FAILED"
    PATENT_EXTRACTION_FAILED = "PATENT_EXTRACTION_FAILED"
    EXAMPLES_EXTRACTION_FAILED = "EXAMPLES_EXTRACTION_FAILED"
    LINK_FAILED = "LINK_FAILED"
    PERSIST_MOLECULES_FAILED = "PERSIST_MOLECULES_FAILED"
    REGISTER_LINKS_FAILED = "REGISTER_LINKS_FAILED"
    PERSIST_DOCUMENT_FAILED = "PERSIST_DOCUMENT_FAILED"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    PIPELINE_CANCELLED = "PIPELINE_CANCELLED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class StageResult:
    """Outcome of a single pipeline stage.

    Attributes:
        stage: Registered pipeline stage name.
        status: ``success``, ``warning`` (stage skipped but pipeline continues),
            or ``error`` (pipeline aborts).
        message: Human-readable description.
        error_code: Machine-readable code when status is not ``success``.
        recoverable: If ``True`` the runner logs a warning and continues; if
            ``False`` the runner emits an error event and aborts.
        context: Extra JSON-serializable data (e.g., exception type, counts).
        warnings: Non-fatal observations attached to a *successful* result
            (surfaced as events without changing stage status). A stage-level
            partial outcome — skipped work, unresolved gaps — belongs in
            ``status="warning"`` with ``recoverable=True`` instead.
    """

    stage: str
    status: Literal["success", "warning", "error"]
    message: str
    error_code: str | None = None
    recoverable: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


__all__ = ["PipelineErrorCode", "StageResult"]

"""Wire protocol between the Patent stage and the analysis runtime.

The request carries no filesystem path: Python binds ``library_root`` inside
its own :class:`PatentTaskScope` and only the scope-limited tool endpoints
resolve it. The runtime returns one terminal outcome and streams progress,
tool and draft events; a dropped transport is never a success.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mbforge.contracts.patent import PatentGap, PatentGapAnswer

#: Runtime protocol version understood by this module.
PROTOCOL_VERSION = "2"


class PatentAnalysisBudget(BaseModel):
    """Engineering limits for one attempt (not scientific thresholds)."""

    model_config = ConfigDict(extra="forbid")

    max_model_turns: int = Field(..., ge=1, le=200)
    wall_clock_seconds: int = Field(..., ge=5, le=7200)
    max_total_tokens: int = Field(..., ge=1000)
    digest_char_budget: int = Field(..., ge=1000)
    request_timeout_seconds: int = Field(
        240,
        ge=10,
        le=7200,
        description="Per provider request timeout. The patent task must not "
        "inherit the chat request timeout: one long turn would otherwise end "
        "the whole attempt.",
    )


class PatentTaskScope(BaseModel):
    """Python-side binding of one attempt; never leaves the process.

    The immutable tuple a task is bound to: the library path stays here, so no
    model-supplied path or foreign document id can ever be honoured.
    """

    model_config = ConfigDict(extra="forbid")

    library_root: str = Field(..., min_length=1)
    doc_id: str = Field(..., min_length=1, max_length=128)
    run_id: str = Field(..., min_length=1, max_length=128)
    attempt_id: str = Field(..., min_length=1, max_length=128)
    evidence_signature: str = Field(..., min_length=1, max_length=128)
    budget: PatentAnalysisBudget


class PatentAnalysisRequest(BaseModel):
    """What the analysis session may know: no path, no credential echo.

    The worklist travels with the request: one bounded gap per unit of work, so
    the session fills the gaps the rules named instead of re-deriving them.
    """

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["2"] = "2"
    doc_id: str = Field(..., min_length=1, max_length=128)
    run_id: str = Field(..., min_length=1, max_length=128)
    attempt_id: str = Field(..., min_length=1, max_length=128)
    evidence_signature: str = Field(..., min_length=1, max_length=128)
    credential: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Short-lived task credential tool callbacks must carry; "
        "it never enters the model context or a log.",
    )
    budget: PatentAnalysisBudget
    gaps: list[PatentGap] = Field(default_factory=list, max_length=200)


PatentAnalysisEventKind = Literal["progress", "tool", "gap", "terminal"]


class PatentAnalysisEvent(BaseModel):
    """One streamed runtime event (progress line, tool result, draft submit)."""

    model_config = ConfigDict(extra="forbid")

    kind: PatentAnalysisEventKind
    phase: str = Field("", max_length=64)
    message: str = Field("", max_length=2000)
    turn: int = Field(0, ge=0)
    tool: str = Field("", max_length=64)
    ok: bool | None = None
    error: str | None = Field(None, max_length=2000)
    data: dict[str, Any] = Field(default_factory=dict)


PatentTerminalStatus = Literal["succeeded", "failed", "cancelled"]


class PatentAnalysisOutcome(BaseModel):
    """The single terminal result of one attempt."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    status: PatentTerminalStatus
    complete: bool = Field(
        True,
        description="False when the run stopped early (budget, timeout, "
        "disconnect) after submitting facts: the submissions are still valid "
        "and are merged as a partial result.",
    )
    turns: int = Field(0, ge=0)
    tool_calls: int = Field(0, ge=0)
    tokens: int | None = Field(
        None,
        ge=0,
        description="Cumulative tokens when the provider reported usage; "
        "``None`` means unknown, never 0.",
    )
    duration_ms: int = Field(0, ge=0)
    model: str = Field("", max_length=200)
    prompt_version: str = Field("", max_length=64)
    error_code: str | None = Field(None, max_length=64)
    error: str | None = Field(None, max_length=2000)


class PatentAnalysisResult(BaseModel):
    """A run's terminal outcome plus the gap answers Python staged for it.

    Answers never travel over the wire: each scope-limited ``submit-gap-answer``
    call stages one answer in this process, and the runtime hands them all back
    before the attempt's credential is revoked — so a run that stops early still
    yields everything it had already validated.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: PatentAnalysisOutcome
    gap_answers: list[PatentGapAnswer] = Field(default_factory=list)
    evidence_reads: dict[str, bool] = Field(default_factory=dict)
    """Returned evidence IDs mapped to whether their text was fully returned."""


class PatentAnalysisCancelRequest(BaseModel):
    """Cancel one in-flight attempt; late results must not be adopted."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(..., min_length=1, max_length=128)
    credential: str | None = Field(None, max_length=128)


__all__ = [
    "PROTOCOL_VERSION",
    "PatentAnalysisBudget",
    "PatentAnalysisCancelRequest",
    "PatentAnalysisEvent",
    "PatentAnalysisEventKind",
    "PatentAnalysisOutcome",
    "PatentAnalysisRequest",
    "PatentAnalysisResult",
    "PatentTaskScope",
    "PatentTerminalStatus",
]

"""Ports for the evidence-constrained Patent analysis runtime.

``PatentAnalysisRuntime`` is the outbound boundary: the Patent stage hands one
attempt to whatever executes the model session (today the Node Pi sidecar).
``PatentTaskRegistry`` is the inbound boundary: it holds each in-flight
attempt's immutable scope, the short-lived credential its tool callbacks carry,
the bounded gap worklist and the staged answers, so the scope-limited tool
endpoints can serve the model without ever trusting a model-supplied path or
doc id.

Neither port performs I/O; the composition root installs the adapters.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from mbforge.contracts.patent import PatentGap, PatentGapAnswer
from mbforge.contracts.patent_runtime import (
    PatentAnalysisEvent,
    PatentAnalysisResult,
    PatentTaskScope,
)


class PatentAnalysisRuntime(Protocol):
    """Executes one bounded analysis attempt and reports its outcome."""

    def ensure_ready(self) -> str | None:
        """Return ``None`` when an attempt can run, else the reason it cannot.

        The runtime owns this check, so a caller never reaches into a concrete
        adapter (or starts a process) itself.
        """
        ...

    def run(
        self,
        scope: PatentTaskScope,
        *,
        gaps: list[PatentGap],
        should_cancel: Callable[[], bool] | None = None,
        on_event: Callable[[PatentAnalysisEvent], None] | None = None,
    ) -> PatentAnalysisResult:
        """Run the attempt to a single terminal outcome.

        The runtime mints the short-lived credential, binds ``scope`` to it for
        the duration of the call and revokes it afterwards. ``gaps`` is the
        bounded worklist: one unit of work per rule refusal, each carrying its
        own evidence and excerpt. ``should_cancel`` is polled while the attempt
        runs, so a caller-side cancellation stops the session instead of waiting
        for the budget. Events are reported through ``on_event`` as they arrive;
        a dropped or truncated transport must surface as a failed outcome, never
        as success. The returned result also carries the gap answers the
        submission endpoint staged, if any.
        """
        ...

    def cancel(self, attempt_id: str) -> bool:
        """Ask the runtime to stop ``attempt_id``; True when it was running."""
        ...


class PatentTaskRegistry(Protocol):
    """In-flight attempts: scope binding, credentials, drafts, cancel flags."""

    def register(
        self,
        credential: str,
        scope: PatentTaskScope,
        *,
        gaps: list[PatentGap] | None = None,
    ) -> None:
        """Bind a fresh credential to its immutable task scope and worklist."""
        ...

    def resolve(self, credential: str) -> PatentTaskScope | None:
        """Return the scope bound to ``credential`` (``None`` when unknown)."""
        ...

    def revoke(self, credential: str) -> None:
        """Drop the task: its credential stops working immediately."""
        ...

    def gaps(self, credential: str) -> list[PatentGap]:
        """The bounded worklist this attempt was registered with."""
        ...

    def gap(self, credential: str, gap_id: str) -> PatentGap | None:
        """One registered gap, or ``None`` when the attempt has no such gap."""
        ...

    def next_gap(self, credential: str) -> PatentGap | None:
        """The first gap without an answer yet, or ``None`` when none is left."""
        ...

    def record_gap_excerpt(
        self, credential: str, gap_id: str, evidence_ids: list[str]
    ) -> str | None:
        """Record a gap's one follow-up excerpt; return a refusal reason or None."""
        ...

    def gap_evidence_ids(self, credential: str, gap_id: str) -> set[str]:
        """Evidence a gap's answer may cite: its excerpt plus its follow-up."""
        ...

    def stage_gap_answer(self, credential: str, answer: PatentGapAnswer) -> None:
        """Keep one validated gap answer; a resubmission replaces it."""
        ...

    def gap_answers(self, credential: str) -> list[PatentGapAnswer]:
        """Every staged gap answer, in submit order."""
        ...

    def record_evidence_reads(
        self, credential: str, items: list[dict[str, Any]]
    ) -> None:
        """Record only evidence actually returned by successful tools."""
        ...

    def evidence_reads(self, credential: str) -> dict[str, bool]:
        """IDs mapped to whether the full text was returned at least once."""
        ...

    def request_cancel(self, credential: str) -> bool:
        """Flag the attempt as cancelled; True when it was still active."""
        ...

    def is_cancelled(self, credential: str) -> bool:
        """Whether the attempt has been cancelled."""
        ...


_runtime: PatentAnalysisRuntime | None = None
_registry: PatentTaskRegistry | None = None


def configure_patent_analysis_runtime(runtime: PatentAnalysisRuntime) -> None:
    """Install the concrete analysis runtime during composition."""
    global _runtime
    _runtime = runtime


def configure_patent_task_registry(registry: PatentTaskRegistry) -> None:
    """Install the concrete task registry during composition."""
    global _registry
    _registry = registry


def get_patent_analysis_runtime() -> PatentAnalysisRuntime:
    """Return the configured analysis runtime."""
    if _runtime is None:
        raise RuntimeError(
            "patent analysis runtime is not configured; build the application "
            "through mbforge.server.app or configure it in the test "
            "composition root"
        )
    return _runtime


def get_patent_task_registry() -> PatentTaskRegistry:
    """Return the configured task registry."""
    if _registry is None:
        raise RuntimeError(
            "patent task registry is not configured; build the application "
            "through mbforge.server.app or configure it in the test "
            "composition root"
        )
    return _registry


__all__ = [
    "PatentAnalysisRuntime",
    "PatentTaskRegistry",
    "configure_patent_analysis_runtime",
    "configure_patent_task_registry",
    "get_patent_analysis_runtime",
    "get_patent_task_registry",
]

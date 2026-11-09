"""Process-local Patent-analysis runtime: task registry and sidecar client.

``InMemoryPatentTaskRegistry`` holds each in-flight attempt's immutable scope and
the short-lived credential its tool callbacks carry. ``SidecarPatentAnalysisRuntime``
is the client side of the wire protocol: it mints the credential, binds the
scope, streams the Node Pi session's events to the caller and returns the single
terminal outcome. A dropped or truncated stream is never a success, and the
credential is revoked as soon as the attempt ends.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from mbforge.contracts.patent import PatentGap, PatentGapAnswer
from mbforge.contracts.patent_runtime import (
    PatentAnalysisEvent,
    PatentAnalysisOutcome,
    PatentAnalysisRequest,
    PatentAnalysisResult,
    PatentTaskScope,
    PatentTerminalStatus,
)
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger
from mbforge.foundation.paths import DEFAULT_AGENT_HOST, DEFAULT_AGENT_PORT
from mbforge.server import agent_process
from mbforge.service.ports.patent_analysis import get_patent_task_registry

logger = get_logger(__name__)


@dataclass
class _Attempt:
    """One registered attempt's mutable state (guarded by the registry lock)."""

    scope: PatentTaskScope
    gaps: list[PatentGap] = field(default_factory=list)
    gap_answers: list[PatentGapAnswer] = field(default_factory=list)
    #: One bounded follow-up excerpt per gap, by gap id.
    extra_excerpts: dict[str, list[str]] = field(default_factory=dict)
    evidence_reads: dict[str, bool] = field(default_factory=dict)
    cancelled: threading.Event = field(default_factory=threading.Event)


class InMemoryPatentTaskRegistry:
    """Thread-safe task registry keyed by credential."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: dict[str, _Attempt] = {}

    def register(
        self,
        credential: str,
        scope: PatentTaskScope,
        *,
        gaps: list[PatentGap] | None = None,
    ) -> None:
        if not credential:
            raise ValueError("credential is required")
        with self._lock:
            self._attempts[credential] = _Attempt(
                scope=scope,
                gaps=list(gaps or []),
            )

    def resolve(self, credential: str) -> PatentTaskScope | None:
        with self._lock:
            attempt = self._attempts.get(credential)
            return attempt.scope if attempt is not None else None

    def revoke(self, credential: str) -> None:
        with self._lock:
            self._attempts.pop(credential, None)

    def gaps(self, credential: str) -> list[PatentGap]:
        """The bounded worklist this attempt was registered with."""
        with self._lock:
            attempt = self._attempts.get(credential)
            return list(attempt.gaps) if attempt is not None else []

    def gap(self, credential: str, gap_id: str) -> PatentGap | None:
        with self._lock:
            attempt = self._attempts.get(credential)
            if attempt is None:
                return None
            return next((gap for gap in attempt.gaps if gap.gap_id == gap_id), None)

    def next_gap(self, credential: str) -> PatentGap | None:
        """The first gap without an answer yet (the session iterates these)."""
        with self._lock:
            attempt = self._attempts.get(credential)
            if attempt is None:
                return None
            answered = {answer.gap_id for answer in attempt.gap_answers}
            return next(
                (gap for gap in attempt.gaps if gap.gap_id not in answered), None
            )

    def record_gap_excerpt(
        self, credential: str, gap_id: str, evidence_ids: list[str]
    ) -> str | None:
        """Record the one follow-up excerpt a gap may ask for.

        Returns ``None`` when it was recorded, else the reason it was refused:
        a second excerpt for the same gap, or an unknown gap.
        """
        with self._lock:
            attempt = self._attempts.get(credential)
            if attempt is None:
                return "unknown or expired patent analysis credential"
            if not any(gap.gap_id == gap_id for gap in attempt.gaps):
                return "unknown gap for this attempt"
            if gap_id in attempt.extra_excerpts:
                return "this gap already asked for a follow-up excerpt"
            attempt.extra_excerpts[gap_id] = list(evidence_ids)
            return None

    def gap_evidence_ids(self, credential: str, gap_id: str) -> set[str]:
        """Evidence the gap's answer may cite: the excerpt plus its follow-up."""
        with self._lock:
            attempt = self._attempts.get(credential)
            if attempt is None:
                return set()
            gap = next((item for item in attempt.gaps if item.gap_id == gap_id), None)
            if gap is None:
                return set()
            return set(gap.evidence_ids) | set(attempt.extra_excerpts.get(gap_id, []))

    def stage_gap_answer(self, credential: str, answer: PatentGapAnswer) -> None:
        """Keep one validated gap answer; a resubmission replaces it."""
        with self._lock:
            attempt = self._attempts.get(credential)
            if attempt is None:
                raise KeyError("unknown patent analysis credential")
            attempt.gap_answers = [
                existing
                for existing in attempt.gap_answers
                if existing.gap_id != answer.gap_id
            ]
            attempt.gap_answers.append(answer)

    def gap_answers(self, credential: str) -> list[PatentGapAnswer]:
        """Every staged gap answer, in submit order."""
        with self._lock:
            attempt = self._attempts.get(credential)
            return list(attempt.gap_answers) if attempt is not None else []

    def record_evidence_reads(
        self, credential: str, items: list[dict[str, Any]]
    ) -> None:
        with self._lock:
            attempt = self._attempts.get(credential)
            if attempt is not None:
                for item in items:
                    evidence_id = item["evidence_id"]
                    attempt.evidence_reads[evidence_id] = (
                        attempt.evidence_reads.get(evidence_id, False)
                        or not item["truncated"]
                    )

    def evidence_reads(self, credential: str) -> dict[str, bool]:
        with self._lock:
            attempt = self._attempts.get(credential)
            return dict(attempt.evidence_reads) if attempt is not None else {}

    def request_cancel(self, credential: str) -> bool:
        with self._lock:
            attempt = self._attempts.get(credential)
            if attempt is None:
                return False
            attempt.cancelled.set()
            return True

    def is_cancelled(self, credential: str) -> bool:
        with self._lock:
            attempt = self._attempts.get(credential)
            return attempt.cancelled.is_set() if attempt is not None else False


def create_patent_task_registry() -> InMemoryPatentTaskRegistry:
    """Build the process-local task registry for the composition root."""
    return InMemoryPatentTaskRegistry()


def default_agent_base_url() -> str:
    """Resolve the Node agent sidecar's base URL (environment-overridable)."""
    explicit = os.environ.get("MBFORGE_AGENT_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.environ.get("MBFORGE_AGENT_HOST", DEFAULT_AGENT_HOST)
    port = os.environ.get("MBFORGE_AGENT_PORT", str(DEFAULT_AGENT_PORT))
    return f"http://{host}:{port}"


class SidecarPatentAnalysisRuntime:
    """HTTP transport for the Node Pi Patent-analysis runtime."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_margin_seconds: float = 60.0,
    ) -> None:
        self._base_url = (base_url or default_agent_base_url()).rstrip("/")
        self._transport = transport
        self._timeout_margin = timeout_margin_seconds
        self._lock = threading.Lock()
        self._credentials: dict[str, str] = {}

    # -- PatentAnalysisRuntime -------------------------------------------

    def ensure_ready(self) -> str | None:
        """Start or adopt the agent sidecar; ``None`` when attempts can run."""
        status = agent_process.ensure_agent_sidecar(base_url=self._base_url)
        return (
            None
            if status.ready
            else (status.reason or "the agent sidecar is not ready")
        )

    def run(
        self,
        scope: PatentTaskScope,
        *,
        gaps: list[PatentGap],
        should_cancel: Callable[[], bool] | None = None,
        on_event: Callable[[PatentAnalysisEvent], None] | None = None,
    ) -> PatentAnalysisResult:
        """Bind the attempt, stream it, and always return one terminal outcome."""
        registry = get_patent_task_registry()
        credential = short_id() + short_id()
        registry.register(credential, scope, gaps=gaps)
        with self._lock:
            self._credentials[scope.attempt_id] = credential
        try:
            request = PatentAnalysisRequest(
                doc_id=scope.doc_id,
                run_id=scope.run_id,
                attempt_id=scope.attempt_id,
                evidence_signature=scope.evidence_signature,
                credential=credential,
                budget=scope.budget,
                gaps=gaps,
            )
            outcome = self._stream(
                request, should_cancel=should_cancel, on_event=on_event
            )
            # The staged answers live in this process and their only handle is the
            # credential, so read them back before the finally-block revokes it.
            return PatentAnalysisResult(
                outcome=outcome,
                gap_answers=registry.gap_answers(credential),
                evidence_reads=registry.evidence_reads(credential),
            )
        finally:
            with self._lock:
                self._credentials.pop(scope.attempt_id, None)
            registry.revoke(credential)

    def cancel(self, attempt_id: str) -> bool:
        """Stop ``attempt_id``: flag the task and tell the sidecar to abort."""
        with self._lock:
            credential = self._credentials.get(attempt_id)
        flagged = (
            get_patent_task_registry().request_cancel(credential)
            if credential
            else False
        )
        return self._post_cancel(attempt_id) or flagged

    # -- transport -------------------------------------------------------

    def _stream(
        self,
        request: PatentAnalysisRequest,
        *,
        should_cancel: Callable[[], bool] | None,
        on_event: Callable[[PatentAnalysisEvent], None] | None,
    ) -> PatentAnalysisOutcome:
        started = time.monotonic()
        read_timeout = float(request.budget.wall_clock_seconds) + self._timeout_margin
        try:
            with (
                self._client(read_timeout) as client,
                client.stream(
                    "POST",
                    f"{self._base_url}/v1/patent-analysis",
                    json=request.model_dump(),
                ) as response,
            ):
                if response.status_code != 200:
                    return self._failed(
                        "sidecar_rejected",
                        f"HTTP {response.status_code}: {self._error_detail(response)}",
                        started,
                    )
                return self._consume(
                    response,
                    request=request,
                    should_cancel=should_cancel,
                    on_event=on_event,
                    started=started,
                )
        except httpx.HTTPError as exc:
            return self._failed(
                "sidecar_unavailable", f"{type(exc).__name__}: {exc}", started
            )

    def _consume(
        self,
        response: httpx.Response,
        *,
        request: PatentAnalysisRequest,
        should_cancel: Callable[[], bool] | None,
        on_event: Callable[[PatentAnalysisEvent], None] | None,
        started: float,
    ) -> PatentAnalysisOutcome:
        """Read the SSE stream and return its single terminal outcome."""
        event_name = ""
        data_lines: list[str] = []
        for line in response.iter_lines():
            if should_cancel is not None and should_cancel():
                self.cancel(request.attempt_id)
                return self._failed(
                    "cancelled", "cancelled by the caller", started, status="cancelled"
                )
            if line == "":
                outcome = self._dispatch(
                    event_name, data_lines, on_event=on_event, started=started
                )
                if outcome is not None:
                    return outcome
                event_name, data_lines = "", []
                continue
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        return self._failed(
            "transport_truncated",
            "the sidecar stream ended without a terminal event",
            started,
        )

    def _dispatch(
        self,
        event_name: str,
        data_lines: list[str],
        *,
        on_event: Callable[[PatentAnalysisEvent], None] | None,
        started: float,
    ) -> PatentAnalysisOutcome | None:
        """Handle one SSE frame; returns an outcome only for the terminal one."""
        if not data_lines:
            return None
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            return self._failed("transport_malformed", str(exc), started)
        if event_name == "done":
            try:
                return PatentAnalysisOutcome.model_validate(payload)
            except Exception as exc:  # noqa: BLE001 — a bad terminal payload fails
                return self._failed("transport_malformed", str(exc), started)
        if on_event is None:
            return None
        try:
            on_event(PatentAnalysisEvent.model_validate(payload))
        except Exception as exc:  # noqa: BLE001 — observability must not abort work
            logger.warning("patent analysis event dropped: %s", exc)
        return None

    def _post_cancel(self, attempt_id: str) -> bool:
        try:
            with self._client(10.0) as client:
                response = client.post(
                    f"{self._base_url}/v1/patent-analysis/cancel",
                    json={"attempt_id": attempt_id},
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _client(self, read_timeout: float) -> httpx.Client:
        timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=10.0)
        return httpx.Client(timeout=timeout, transport=self._transport)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            return response.read().decode("utf-8", errors="replace")[:500]
        except httpx.HTTPError:
            return f"HTTP {response.status_code}"

    @staticmethod
    def _failed(
        error_code: str,
        error: str,
        started: float,
        *,
        status: PatentTerminalStatus = "failed",
    ) -> PatentAnalysisOutcome:
        return PatentAnalysisOutcome(
            ok=False,
            status=status,
            complete=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code=error_code,
            error=error[:2000],
        )


def create_patent_analysis_runtime() -> SidecarPatentAnalysisRuntime:
    """Build the sidecar transport adapter for the composition root."""
    return SidecarPatentAnalysisRuntime()


__all__ = [
    "InMemoryPatentTaskRegistry",
    "SidecarPatentAnalysisRuntime",
    "create_patent_analysis_runtime",
    "create_patent_task_registry",
    "default_agent_base_url",
]

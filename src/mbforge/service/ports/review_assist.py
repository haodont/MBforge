"""Port for the review-center AI assistance runtime.

The review use case hands one bounded packet to whatever executes the model
call (today the Node sidecar). The port performs no I/O itself; the composition
root installs the adapter, so no service module reaches a concrete transport.
"""

from __future__ import annotations

from typing import Protocol

from mbforge.contracts.review_assist import AssistPacket, AssistSuggestion

_runtime: ReviewAssistRuntime | None = None


class ReviewAssistRuntime(Protocol):
    """Executes one bounded assist call and reports its outcome.

    A failed call is data, not an exception: the review queue keeps working when
    the sidecar is down or no vision model is configured.
    """

    def run(
        self, packet: AssistPacket, *, timeout_seconds: float = 120.0
    ) -> AssistSuggestion: ...


def configure_review_assist_runtime(runtime: ReviewAssistRuntime | None) -> None:
    """Install the adapter; the composition root calls this once."""
    global _runtime
    _runtime = runtime


def get_review_assist_runtime() -> ReviewAssistRuntime:
    """Return the installed adapter.

    Raises ``RuntimeError`` when the composition root never installed one: a
    missing runtime is a wiring defect, not a per-call failure.
    """
    if _runtime is None:
        raise RuntimeError(
            "review assist runtime is not configured; build the application "
            "through mbforge.server.app"
        )
    return _runtime


__all__ = [
    "ReviewAssistRuntime",
    "configure_review_assist_runtime",
    "get_review_assist_runtime",
]

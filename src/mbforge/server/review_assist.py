"""Sidecar client for review-center AI assistance.

Mirrors the Patent-analysis runtime: Python owns the packet and the storage, the
Node sidecar owns every provider call. A transport failure is returned as data
so the review queue keeps working when the sidecar is down.
"""

from __future__ import annotations

import httpx

from mbforge.contracts.review_assist import AssistPacket, AssistSuggestion
from mbforge.foundation.logger import get_logger
from mbforge.foundation.paths import DEFAULT_AGENT_HOST, DEFAULT_AGENT_PORT

logger = get_logger(__name__)

_STATUSES = {"answered", "refused", "unavailable", "error"}


class SidecarReviewAssistRuntime:
    """POST /v1/review-assist on the Node sidecar."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._host = host or DEFAULT_AGENT_HOST
        self._port = int(port or DEFAULT_AGENT_PORT)
        self._client = http_client

    def run(
        self, packet: AssistPacket, *, timeout_seconds: float = 120.0
    ) -> AssistSuggestion:
        url = f"http://{self._host}:{self._port}/v1/review-assist"
        payload = {"packet": packet.model_dump()}
        try:
            if self._client is not None:
                response = self._client.post(url, json=payload, timeout=timeout_seconds)
            else:
                response = httpx.post(url, json=payload, timeout=timeout_seconds)
        except httpx.HTTPError as exc:
            return AssistSuggestion(
                status="unavailable",
                error=("sidecar unreachable: " + exc.__class__.__name__)[:300],
            )
        if response.status_code != 200:
            return AssistSuggestion(
                status="error",
                error=("sidecar returned HTTP " + str(response.status_code))[:300],
            )
        try:
            data = response.json()
        except ValueError:
            return AssistSuggestion(status="error", error="sidecar returned no JSON")
        if not isinstance(data, dict):
            return AssistSuggestion(status="error", error="sidecar returned no object")
        status = str(data.get("status") or "error")
        return AssistSuggestion(
            status=status if status in _STATUSES else "error",
            model=str(data.get("model") or ""),
            vision=bool(data.get("vision")),
            answer=str(data.get("answer") or ""),
            error=str(data.get("error") or ""),
        )


def create_review_assist_runtime() -> SidecarReviewAssistRuntime:
    """Build the adapter the composition root installs."""
    return SidecarReviewAssistRuntime()


__all__ = ["SidecarReviewAssistRuntime", "create_review_assist_runtime"]

"""Transient scoped credentials and an async transport to the Node-owned LLM."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from collections.abc import AsyncIterator

import httpx
from pydantic import TypeAdapter

from mbforge.contracts.research import ResearchEvent, ResearchTurnScope
from mbforge.foundation.errors import ConflictError, ResourceNotAvailableError
from mbforge.server.agent_process import ensure_agent_sidecar


class InMemoryResearchRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, tuple[ResearchTurnScope, float]] = {}

    def _expire(self) -> None:
        now = time.monotonic()
        self._turns = {
            token: value for token, value in self._turns.items() if value[1] > now
        }

    def register(self, scope: ResearchTurnScope) -> str:
        with self._lock:
            self._expire()
            if any(
                value[0].library_root == scope.library_root
                and value[0].session_id == scope.session_id
                for value in self._turns.values()
            ):
                raise ConflictError(
                    "A reply is already running in this research conversation"
                )
            credential = secrets.token_urlsafe(32)
            self._turns[credential] = (
                scope.model_copy(deep=True),
                time.monotonic() + 900,
            )
            return credential

    def resolve(self, credential: str) -> ResearchTurnScope | None:
        with self._lock:
            self._expire()
            value = self._turns.get(credential)
            return value[0].model_copy(deep=True) if value else None

    def active(self, library_root: str, session_id: str, request_id: str) -> bool:
        with self._lock:
            self._expire()
            return any(
                value[0].library_root == library_root
                and value[0].session_id == session_id
                and value[0].request_id == request_id
                for value in self._turns.values()
            )

    def revoke(self, credential: str) -> None:
        with self._lock:
            self._turns.pop(credential, None)


class SidecarResearchRuntime:
    def is_active(self, session_id: str) -> bool:
        sidecar = ensure_agent_sidecar()
        if not sidecar.ready:
            raise ResourceNotAvailableError(
                "Cannot verify whether the research reply has stopped"
            )
        with httpx.Client(timeout=15, trust_env=False) as client:
            response = client.post(
                f"{sidecar.base_url}/v1/research-status",
                json={"session_id": session_id},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("active"), bool):
            raise ValueError("Invalid research runtime status")
        return payload["active"]

    async def stream(self, credential: str) -> AsyncIterator[ResearchEvent]:
        sidecar = await asyncio.to_thread(ensure_agent_sidecar)
        if not sidecar.ready:
            raise ResourceNotAvailableError(
                "Research assistant is unavailable", detail=sidecar.reason
            )
        base = sidecar.base_url
        adapter: TypeAdapter[ResearchEvent] = TypeAdapter(ResearchEvent)
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(650, connect=15), trust_env=False
            ) as client,
            client.stream(
                "POST", f"{base}/v1/research-chat", json={"credential": credential}
            ) as response,
        ):
            response.raise_for_status()
            event_name = ""
            data: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    payload = json.loads("\n".join(data))
                    yield adapter.validate_python({**payload, "type": event_name})
                    event_name, data = "", []
            if data:
                raise ValueError("Research event stream ended within a frame")

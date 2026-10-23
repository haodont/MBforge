"""Ownership rules for the Node agent sidecar (backend running without Vite).

Protects: a matching agent is adopted but never restarted, a foreign process on
the port is refused instead of reused, only the process this backend started is
stopped, and autostart can be turned off.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mbforge.server import agent_process


class _StubProcess:
    """Minimal Popen stand-in: the governor only polls, terminates and waits."""

    def __init__(self, pid: int = 4242, exit_code: int | None = None) -> None:
        self.pid = pid
        self.returncode = exit_code
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode


def _health(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "runtime": agent_process.AGENT_RUNTIME_NAME,
        "settings_path": agent_process.settings_path(),
    }
    payload.update(overrides)
    return payload


def _offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("nothing listening", request=request)


def _ensure(handler: Any, *, spawn: Any = None) -> agent_process.AgentSidecarStatus:
    return agent_process.ensure_agent_sidecar(
        base_url="http://agent.test",
        transport=httpx.MockTransport(handler),
        spawn=spawn or (lambda url: _StubProcess()),
        wait_seconds=1.0,
        poll_interval=0.01,
    )


def test_only_a_matching_agent_is_adopted() -> None:
    """A healthy agent with our runtime + settings file is adopted; a foreign
    runtime or an agent serving another settings file is refused, never
    reused, and never (re)started."""
    started: list[str] = []

    matching = _ensure(
        lambda request: httpx.Response(200, json=_health()),
        spawn=lambda url: started.append(url),
    )
    assert matching.ready is True
    assert matching.owned is False

    foreign_runtime = _ensure(
        lambda request: httpx.Response(200, json=_health(runtime="some-other-service")),
        spawn=lambda url: started.append(url),
    )
    assert foreign_runtime.ready is False
    assert "occupies" in foreign_runtime.reason

    foreign_settings = _ensure(
        lambda request: httpx.Response(
            200, json=_health(settings_path="/elsewhere/settings.json")
        ),
        spawn=lambda url: started.append(url),
    )
    assert foreign_settings.ready is False
    assert foreign_settings.reason

    assert started == []


def test_starting_an_agent_makes_this_backend_the_owner() -> None:
    """Starting the sidecar makes this backend the owner and the only one that
    may stop it."""
    process = _StubProcess()
    probes = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        probes["count"] += 1
        if probes["count"] == 1:
            raise httpx.ConnectError("nothing listening", request=request)
        return httpx.Response(200, json=_health())

    started: list[str] = []

    def spawn(url: str) -> _StubProcess:
        started.append(url)
        return process

    status = _ensure(handler, spawn=spawn)

    assert status.ready is True
    assert status.owned is True
    assert status.pid == process.pid
    assert started == ["http://agent.test"]

    assert agent_process.stop_agent_sidecar() is True
    assert process.terminated is True
    # Only what this backend started is ours to stop.
    assert agent_process.stop_agent_sidecar() is False


def test_failed_start_reports_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autostart can be disabled, and a sidecar that exits before becoming
    ready is reported instead of hanging."""
    monkeypatch.setenv("MBFORGE_AGENT_AUTOSTART", "0")
    started: list[str] = []
    disabled = _ensure(_offline, spawn=lambda url: started.append(url))
    assert disabled.ready is False
    assert "AUTOSTART" in disabled.reason
    assert started == []

    monkeypatch.delenv("MBFORGE_AGENT_AUTOSTART")
    exited = _ensure(_offline, spawn=lambda url: _StubProcess(exit_code=3))
    assert exited.ready is False
    assert "exited with code 3" in exited.reason

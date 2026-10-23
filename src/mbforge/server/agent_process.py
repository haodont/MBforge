"""Ownership governance for the Node agent sidecar.

The backend must run without Vite, so it can have to start the Pi agent itself.
Three rules keep that safe:

* adopt a running agent only when ``/health`` identifies the same runtime *and*
  the same ``settings.json`` — a process that merely occupies the port is
  foreign, and reusing it would silently point at another library;
* never start a second instance when one is already usable;
* stop only the process this backend started.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from mbforge.foundation.logger import get_logger
from mbforge.foundation.paths import (
    DEFAULT_AGENT_HOST,
    DEFAULT_AGENT_PORT,
    DEFAULT_SIDECAR_PORT,
    GLOBAL_APP_DIR,
    GLOBAL_SETTINGS_PATH,
    SOURCE_ROOT,
)

logger = get_logger(__name__)

#: ``runtime`` value the Node sidecar reports on ``/health``.
AGENT_RUNTIME_NAME = "pi"

_lock = threading.Lock()
_owned_process: subprocess.Popen[bytes] | None = None
_owned_log: Any = None


@dataclass(frozen=True)
class AgentSidecarStatus:
    """Outcome of one readiness/ownership check."""

    ready: bool
    owned: bool
    base_url: str
    pid: int | None = None
    reason: str = ""


def settings_path() -> str:
    """The settings file both sides must agree on (environment-overridable)."""
    explicit = os.environ.get("MBFORGE_SETTINGS_PATH", "").strip()
    return explicit or str(GLOBAL_SETTINGS_PATH)


def probe_agent_health(
    base_url: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    """Return the agent's ``/health`` payload, or ``None`` when nothing answers."""
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.get(f"{base_url.rstrip('/')}/health")
            if response.status_code != 200:
                return None
            payload = response.json()
            return payload if isinstance(payload, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


def ensure_agent_sidecar(
    *,
    base_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
    spawn: Callable[[str], subprocess.Popen[bytes]] | None = None,
    wait_seconds: float = 30.0,
    poll_interval: float = 0.25,
) -> AgentSidecarStatus:
    """Adopt a matching agent, or start one this process then owns."""
    resolved = (base_url or default_base_url()).rstrip("/")
    payload = probe_agent_health(resolved, transport=transport)
    if payload is not None:
        if not _identity_matches(payload):
            return AgentSidecarStatus(
                ready=False,
                owned=False,
                base_url=resolved,
                reason=(
                    "another process occupies the agent port and does not "
                    "identify as this MBForge agent"
                ),
            )
        return _ready_status(resolved)

    if os.environ.get("MBFORGE_AGENT_AUTOSTART") == "0":
        return AgentSidecarStatus(
            ready=False,
            owned=False,
            base_url=resolved,
            reason="MBFORGE_AGENT_AUTOSTART=0 and no agent is listening",
        )

    try:
        process = (spawn or _spawn_agent)(resolved)
    except Exception as exc:  # noqa: BLE001 — a failed start is a status, not a crash
        return AgentSidecarStatus(
            ready=False,
            owned=False,
            base_url=resolved,
            reason=f"could not start the agent sidecar: {exc}",
        )
    _remember_owned(process)

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        payload = probe_agent_health(resolved, transport=transport)
        if payload is not None and _identity_matches(payload):
            return AgentSidecarStatus(
                ready=True, owned=True, base_url=resolved, pid=process.pid
            )
        if process.poll() is not None:
            _forget_owned()
            return AgentSidecarStatus(
                ready=False,
                owned=False,
                base_url=resolved,
                reason=(
                    "the agent sidecar exited with code "
                    f"{process.returncode} before becoming ready"
                ),
            )
        time.sleep(poll_interval)
    return AgentSidecarStatus(
        ready=False,
        owned=True,
        base_url=resolved,
        pid=process.pid,
        reason="the agent sidecar did not become ready in time",
    )


def stop_agent_sidecar(*, timeout: float = 5.0) -> bool:
    """Stop the agent only when this backend started it; True when it did."""
    with _lock:
        process = _owned_process
    if process is None:
        return False
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            with contextlib.suppress(Exception):
                process.wait(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — shutdown is best-effort
            logger.warning("stopping the agent sidecar failed: %s", exc)
    _forget_owned()
    return True


def _ready_status(base_url: str) -> AgentSidecarStatus:
    with _lock:
        process = _owned_process
    owned = process is not None and process.poll() is None
    return AgentSidecarStatus(
        ready=True, owned=owned, base_url=base_url, pid=process.pid if owned else None
    )


def _remember_owned(process: subprocess.Popen[bytes], log: Any = None) -> None:
    global _owned_process, _owned_log
    with _lock:
        _owned_process = process
        _owned_log = log


def _forget_owned() -> None:
    global _owned_process, _owned_log
    with _lock:
        handle, _owned_process, _owned_log = _owned_log, None, None
    if handle is not None:
        with contextlib.suppress(OSError):
            handle.close()


def _identity_matches(payload: dict[str, Any]) -> bool:
    if payload.get("runtime") != AGENT_RUNTIME_NAME:
        return False
    return _normalise(payload.get("settings_path")) == _normalise(settings_path())


def _normalise(path: object) -> str:
    return os.path.normcase(os.path.abspath(str(path or "")))


def default_base_url() -> str:
    """Resolve the sidecar base URL the same way the adapter does."""
    from mbforge.server.patent_analysis import default_agent_base_url

    return default_agent_base_url()


def _spawn_command() -> list[str]:
    import shutil

    node = shutil.which("node")
    if not node:
        raise RuntimeError("node executable not found on PATH")
    entry = SOURCE_ROOT / "agent" / "dist" / "server.js"
    if not entry.is_file():
        raise RuntimeError(
            f"agent sidecar build missing: {entry} (run `npm --prefix agent run build`)"
        )
    return [node, str(entry)]


def _spawn_agent(base_url: str) -> subprocess.Popen[bytes]:
    """Start the sidecar hidden, pointing its tool callbacks back at this app."""
    parsed = urlparse(base_url)
    env = dict(os.environ)
    env["MBFORGE_AGENT_HOST"] = parsed.hostname or DEFAULT_AGENT_HOST
    env["MBFORGE_AGENT_PORT"] = str(parsed.port or DEFAULT_AGENT_PORT)
    env.setdefault("MBFORGE_BACKEND_HOST", "127.0.0.1")
    # Tool callbacks must reach *this* application, never the agent's own port:
    # defaulting to DEFAULT_AGENT_PORT sent every callback back to the sidecar
    # (404), which looked exactly like a model that refuses to work.
    env.setdefault(
        "MBFORGE_BACKEND_PORT",
        os.environ.get("MBFORGE_PORT", str(DEFAULT_SIDECAR_PORT)),
    )
    log_path = GLOBAL_APP_DIR / "logs" / "agent-sidecar.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "ab")  # noqa: SIM115 — closed by stop_agent_sidecar
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    logger.info("Starting the agent sidecar at %s", base_url)
    process = subprocess.Popen(  # noqa: S603 — fixed argv, never a shell
        _spawn_command(),
        env=env,
        cwd=str(SOURCE_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    _remember_owned(process, handle)
    return process


__all__ = [
    "AGENT_RUNTIME_NAME",
    "AgentSidecarStatus",
    "default_base_url",
    "ensure_agent_sidecar",
    "probe_agent_health",
    "settings_path",
    "stop_agent_sidecar",
]

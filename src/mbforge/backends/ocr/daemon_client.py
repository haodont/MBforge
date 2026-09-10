"""Client + process manager for the persistent crop-label OCR daemon.

When ``moldet.ocr_mode == "daemon"``, ``get_label_reader()`` lazily spawns a
long-lived background process (``python -m mbforge.backends.ocr.daemon``),
waits for it to become healthy, and serves reads over HTTP. The daemon keeps
the configured engine (default torch on CUDA via ``moldet.ocr_daemon_device``)
resident so warm-up cost is paid once across the whole MBForge run.

Lifecycle is MolDet-style: ``get_daemon_client()`` is a process-wide lazy
singleton and ``unload()`` kills the background process; the daemon is also
reaped at interpreter exit as a safety net.
"""

from __future__ import annotations

import atexit
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from ...utils.logger import get_logger

logger = get_logger(__name__)

_client_singleton = None
_client_lock = threading.Lock()
_proc_handle = None  # the spawned subprocess (kept alive for the session)

# Default address of the daemon; override via config.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18799


def _daemon_config() -> tuple[str, int, int]:
    """Return ``(host, port, device_id)`` from config (healthy defaults)."""
    from ...utils.config import load_global_config

    try:
        cfg = load_global_config()
        moldet = getattr(cfg, "moldet", None)
        if moldet is None:
            return DEFAULT_HOST, DEFAULT_PORT, 0
        host = getattr(moldet, "ocr_daemon_host", DEFAULT_HOST) or DEFAULT_HOST
        port = int(getattr(moldet, "ocr_daemon_port", DEFAULT_PORT) or DEFAULT_PORT)
        device = int(getattr(moldet, "ocr_daemon_device", 0) or 0)
        return host, port, device
    except Exception:
        return DEFAULT_HOST, DEFAULT_PORT, 0


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _daemon_is_healthy(client: httpx.Client, host: str, port: int) -> bool:
    try:
        resp = client.get(_base_url(host, port) + "/health", timeout=1.0)
        return resp.status_code == 200 and resp.json().get("status") == "ready"
    except Exception:
        return False


def _spawn_daemon(
    host: str, port: int, device_id: int, timeout: float = 60.0
) -> subprocess.Popen:
    """Start the daemon subprocess and wait until it reports ready."""
    global _proc_handle
    if _proc_handle is not None and _proc_handle.poll() is None:
        return _proc_handle

    cmd = [
        sys.executable,
        "-m",
        "mbforge.backends.ocr.daemon",
        "--host",
        host,
        "--port",
        str(port),
        "--device-id",
        str(device_id),
    ]
    # Keep the daemon's log next to the main app logs when possible; otherwise
    # route to DEVNULL so our subprocess does not inherit the app's stdio.
    log_path = Path.home() / "MBForge" / "logs" / "ocr-daemon.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the handle open for the subprocess lifetime (Popen requires it).
        stdout_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        stderr_handle = subprocess.STDOUT
    except Exception:
        stdout_handle = subprocess.DEVNULL
        stderr_handle = subprocess.DEVNULL

    logger.info("Spawning OCR daemon: %s", " ".join(cmd))
    _proc_handle = subprocess.Popen(
        cmd,
        stdout=stdout_handle,
        stderr=stderr_handle,
        start_new_session=True,
    )

    client = httpx.Client()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _daemon_is_healthy(client, host, port):
            client.close()
            return _proc_handle
        if _proc_handle.poll() is not None:
            break
        time.sleep(0.25)
    client.close()
    raise RuntimeError(
        f"OCR daemon failed to become healthy within {timeout}s on {host}:{port}"
    )


class DaemonOCRClient:
    """Thin HTTP client that reads labels from the OCR daemon."""

    def __init__(self, host: str, port: int, proc: subprocess.Popen) -> None:
        self._host = host
        self._port = port
        self._proc = proc
        self._http = httpx.Client(timeout=120.0)

    @property
    def base_url(self) -> str:
        return _base_url(self._host, self._port)

    @property
    def is_available(self) -> bool:
        return self._proc.poll() is None and _daemon_is_healthy(
            self._http, self._host, self._port
        )

    def read(self, image) -> list[tuple[str, float, tuple[int, int, int, int], bool]]:
        """OCR an offcut via the daemon; same contract as in-process reads."""
        import io

        buf = io.BytesIO()
        # Convert through RGB ensuring a deterministic 3-channel PNG for the
        # daemon's engine (matches in-process `.convert("RGB")`).
        image.convert("RGB").save(buf, format="PNG")
        resp = self._http.post(
            self.base_url + "/v1/ocr",
            content=buf.getvalue(),
            headers={"Content-Type": "image/png"},
        )
        resp.raise_for_status()
        payload = resp.json()
        reads = []
        for item in payload.get("reads", []):
            text, conf, (x0, y0, x1, y1), isolated = _coerce_read(item)
            reads.append((text, conf, (x0, y0, x1, y1), isolated))
        return reads

    def close(self, proc: bool = True) -> None:
        self._http.close()
        if proc and self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _coerce_read(item) -> tuple[str, float, tuple[int, int, int, int], bool]:
    text = str(item[0])
    conf = float(item[1])
    box = item[2]
    isolated = bool(item[3])
    return text, conf, (int(box[0]), int(box[1]), int(box[2]), int(box[3])), isolated


def get_daemon_client():
    """Return the process-wide daemon client, spawning the daemon on demand."""
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton
    with _client_lock:
        if _client_singleton is None:
            host, port, device = _daemon_config()
            proc = _spawn_daemon(host, port, device)
            _client_singleton = DaemonOCRClient(host, port, proc)
            atexit.register(unload_daemon)
    return _client_singleton


def health() -> dict[str, str]:
    """Daemon readiness snapshot for reports."""
    if _client_singleton is None:
        return {"status": "down", "engine": "n/a", "error": "not spawned"}
    try:
        host, port, _ = _daemon_config()
        if _client_singleton.is_available:
            resp = _client_singleton._http.get(
                _client_singleton.base_url + "/health", timeout=1.0
            )
            payload = resp.json()
            return {
                "status": "ready",
                "engine": payload.get("engine", "n/a"),
                "error": "",
            }
        return {"status": "down", "engine": "n/a", "error": "daemon unhealthy"}
    except Exception as exc:
        return {"status": "down", "engine": "n/a", "error": str(exc)}


def unload_daemon() -> None:
    """Stop the background daemon process and drop the client singleton."""
    global _client_singleton, _proc_handle
    with _client_lock:
        if _client_singleton is not None:
            _client_singleton.close(proc=True)
            _client_singleton = None
        _proc_handle = None

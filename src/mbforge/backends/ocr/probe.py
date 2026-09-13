"""Live connectivity probes for the cloud OCR backends.

Shared by the ``/api/v1/ocr/test-*`` endpoints. Each probe issues a tiny
authenticated HTTP request; the goal is to verify credentials and
reachability, not extraction accuracy.
"""

from __future__ import annotations

import httpx

from ...utils.config import load_global_config

PROBE_TIMEOUT = 10

# 1x1 PNG used as a minimal probe payload.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDAT\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa3\x9c\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def ocr_settings() -> dict:
    """Read current ocr config from AppConfig."""
    cfg = load_global_config()
    return cfg.ocr.model_dump()


def _result(ok: bool, status: int | None, message: str) -> dict:
    return {"ok": ok, "status": status, "message": message}


async def probe_paddleocr(api_key: str, host: str, model: str) -> dict:
    if not api_key or not host:
        cfg = ocr_settings()
        api_key = api_key or cfg.get("paddleocr_api_key", "")
        host = host or cfg.get("paddleocr_host", "https://aistudio.baidu.com")
        model = model or cfg.get("paddleocr_model", "PaddleOCR-VL-1.6")
    if not api_key:
        return _result(False, None, "PaddleOCR api_key 未设置")
    endpoint = f"{host.rstrip('/')}/paddleocr/api/ocr/{model}"
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            r = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("probe.png", _TINY_PNG, "image/png")},
            )
        return _result(
            r.status_code in (200, 400, 401, 403, 422),
            r.status_code,
            "ok" if r.status_code == 200 else "鉴权或网络问题",
        )
    except Exception as exc:  # noqa: BLE001
        return _result(False, None, str(exc))


def _local_models_url(host: str) -> str:
    """URL of a local GenAI server's layout-parsing endpoint."""
    return f"{(host or '').strip().rstrip('/')}/layout-parsing"


async def probe_paddleocr_local(host: str, model: str = "") -> dict:
    """Probe a local PaddleOCR GenAI ``/layout-parsing`` endpoint.

    Sends the server the same tiny 1x1 PNG a real page would, with layout
    pre-processing disabled, and treats any HTTP 200 with ``errorCode == 0``
    as reachable. This confirms both liveness and that the endpoint speaks the
    expected sync layout-parsing protocol (not the cloud async v2 job API).
    """
    host = (host or ocr_settings().get("paddleocr_local_host", "")).strip()
    if not host:
        return _result(False, None, "paddleocr_local_host 未设置")
    url = _local_models_url(host)
    body = {
        "file": "data:image/png;base64,"
        + __import__("base64").b64encode(_TINY_PNG).decode("ascii"),
        "fileType": 1,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
    }
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            r = await client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:  # noqa: BLE001
                data = {}
            if data.get("errorCode") not in (None, 0):
                return _result(
                    False, r.status_code, f"errorCode={data.get('errorCode')}"
                )
            parsed = len((data.get("result") or {}).get("layoutParsingResults") or [])
            return _result(True, r.status_code, f"就绪，返回版面块数={parsed}")
        return _result(False, r.status_code, f"HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        return _result(False, None, str(exc))

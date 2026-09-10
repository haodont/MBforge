"""OCR backend test endpoints — live probes against cloud APIs.

Thin shells over :mod:`mbforge.backends.ocr.probe`, which owns the
credential fallback rules, vendor URLs, and acceptability criteria.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...backends.ocr import probe

router = APIRouter()


class OcrProbeRequest(BaseModel):
    """Probe payload; ``apiKey`` is the legacy camelCase wire key."""

    api_key: str = Field(default="", alias="apiKey")
    host: str = ""
    model: str = ""


@router.post("/test-paddleocr")
async def test_paddleocr(body: OcrProbeRequest) -> dict:
    return await probe.probe_paddleocr(
        body.api_key.strip(),
        body.host.strip(),
        body.model.strip(),
    )


@router.get("/chain-status")
async def chain_status() -> dict:
    """Inspect which OCR backends the chain would try for the current settings."""
    from ...backends.ocr import list_configured_backends

    settings = probe.ocr_settings()
    return {
        "backends": list(list_configured_backends(settings)),
        "priority": settings.get("priority", ["paddleocr"]),
    }

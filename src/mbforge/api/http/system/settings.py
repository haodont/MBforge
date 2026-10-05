"""Settings endpoints.

Read and write the global settings.json configuration file. GET returns the
current config with secret values redacted; PUT performs a deep merge and
persists the new LLM settings so the Node agent sidecar (agent/) picks them up.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import RootModel, ValidationError

from mbforge.foundation.config import (
    load_global_config,
    reset_settings,
    update_settings,
)

router = APIRouter()


# Match secret-ish keys at word/end boundaries so "keyword" and "monkey"
# are preserved while "api_key", "hf_key", "secret", "token" and "password"
# are redacted. Underscores are treated as separators to catch "secret_token".
_SECRET_KEY_RE = re.compile(
    r"api_key|(?:^|_)(secret|token|password|key)$", re.IGNORECASE
)


def _is_secret_key(key: str) -> bool:
    """Return True if ``key`` looks like it holds a credential."""
    return bool(_SECRET_KEY_RE.search(key))


def _redact_secrets(obj: Any) -> Any:
    """Recursively replace secret-ish values with '***' for GET responses."""
    if isinstance(obj, dict):
        return {
            k: "***" if isinstance(v, str) and _is_secret_key(k) else _redact_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj


@router.get("")
async def settings_get() -> dict:
    cfg = await asyncio.to_thread(load_global_config)
    return {"success": True, "settings": _redact_secrets(cfg.model_dump())}


class SettingsUpdateRequest(RootModel[dict[str, Any]]):
    """Free-form deep-merge payload for PUT /settings (partial AppConfig)."""


@router.put("")
async def settings_update(body: SettingsUpdateRequest) -> dict:
    """局部更新:deep-merge → 校验 → 持久化."""
    try:
        new_cfg = await asyncio.to_thread(update_settings, body.root)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return {"success": True, "settings": _redact_secrets(new_cfg.model_dump())}


@router.post("/reset")
async def settings_reset() -> dict:
    """重置全部设置为默认值."""
    cfg = await asyncio.to_thread(reset_settings)
    return {"success": True, "settings": _redact_secrets(cfg.model_dump())}

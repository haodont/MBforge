"""Settings endpoints.

Read and write the global ``settings.json`` configuration file. GET returns
the current config with secret values redacted; PUT performs a deep merge
and persists the new LLM settings so pipeline steps pick them up.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, RootModel, ValidationError

from mbforge.application.ports import get_runtime
from mbforge.foundation.config import (
    load_global_config,
    reset_settings,
    update_settings,
)

router = APIRouter()


def fetch_provider_models(provider: str, base_url: str, api_key: str) -> list[dict]:
    """Resolve the provider probe through the runtime port.

    Keeping this small module-level seam preserves direct callers and lets
    endpoint tests replace the network operation without touching adapters.
    """
    return get_runtime().llm.fetch_provider_models(provider, base_url, api_key)


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


class LlmModelsRequest(BaseModel):
    """Body for the provider model-list probe."""

    provider: str
    base_url: str = ""
    api_key: str = ""


@router.post("/llm-models")
async def settings_llm_models(body: LlmModelsRequest) -> dict:
    """Probe the provider model-list API and return the available models.

    The Settings UI sends the form values so the probe uses exactly what the
    user configured. A redacted placeholder api_key ("***", as returned by
    GET /settings) or an empty one falls back to the persisted key so the
    probe works without ever exposing the stored secret to the browser.
    """
    api_key = body.api_key
    if not api_key or api_key == "***":
        cfg = await asyncio.to_thread(load_global_config)
        api_key = cfg.llm.api_key
    try:
        models = await asyncio.to_thread(
            fetch_provider_models,
            body.provider,
            body.base_url,
            api_key,
        )
    except ValueError as exc:
        # Expected business failure: return the provider's reason in the app
        # success/error envelope so the Settings UI can show it verbatim.
        return {"success": False, "error": str(exc)}
    return {"success": True, "models": models}

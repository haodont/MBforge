from __future__ import annotations

from types import SimpleNamespace

import pytest

from mbforge.interfaces.http.system import settings as settings_router

# Neutral stand-in for a secret-shaped literal; only round-trip equality is
# asserted.
_PERSISTED_VALUE = "persisted-value-roundtrip"


captured: dict[str, str] = {}


def _fetch_probe(provider: str, base_url: str, api_key: str) -> list[dict[str, str]]:
    """Capture the resolved probe args; real network is never touched in router tests.

    Must stay synchronous: the router wraps it in asyncio.to_thread like the
    real httpx probe.
    """
    captured["provider"] = provider
    captured["base_url"] = base_url
    captured["api_key"] = api_key
    return [{"value": "gpt-4o", "label": "gpt-4o"}]


@pytest.mark.asyncio
async def test_settings_llm_models_probes_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured.clear()
    monkeypatch.setattr(settings_router, "fetch_provider_models", _fetch_probe)

    result = await settings_router.settings_llm_models(
        settings_router.LlmModelsRequest(
            provider="openai_compatible",
            base_url="https://api.example.com/v1",
            api_key="sk-live",
        )
    )

    assert result == {
        "success": True,
        "models": [{"value": "gpt-4o", "label": "gpt-4o"}],
    }
    assert captured == {
        "provider": "openai_compatible",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-live",
    }


@pytest.mark.asyncio
async def test_settings_llm_models_placeholder_key_falls_back_to_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured.clear()
    monkeypatch.setattr(settings_router, "fetch_provider_models", _fetch_probe)
    cfg = SimpleNamespace(llm=SimpleNamespace(api_key=_PERSISTED_VALUE))
    monkeypatch.setattr(settings_router, "load_global_config", lambda: cfg)

    result = await settings_router.settings_llm_models(
        settings_router.LlmModelsRequest(
            provider="anthropic", base_url="", api_key="***"
        )
    )

    assert result["success"] is True
    assert captured["api_key"] == _PERSISTED_VALUE


@pytest.mark.asyncio
async def test_settings_llm_models_error_returns_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_probe(provider: str, base_url: str, api_key: str):
        raise ValueError("unsupported LLM provider: nope")

    monkeypatch.setattr(settings_router, "fetch_provider_models", fail_probe)
    cfg = SimpleNamespace(llm=SimpleNamespace(api_key=""))
    monkeypatch.setattr(settings_router, "load_global_config", lambda: cfg)

    result = await settings_router.settings_llm_models(
        settings_router.LlmModelsRequest(provider="nope", base_url="", api_key="")
    )

    assert result == {"success": False, "error": "unsupported LLM provider: nope"}

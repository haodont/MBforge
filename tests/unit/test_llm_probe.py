from __future__ import annotations

import httpx
import pytest

from mbforge.adapters.runtime.llm.provider_models import fetch_provider_models

# Neutral stand-in for a secret-shaped literal; only round-trip equality is
# asserted.
_PROBE_VALUE = "probe-value-roundtrip"


def _ok_payload(handler):
    """Build a MockTransport that calls ``handler(request) -> dict`` and returns JSON 200."""

    def respond(request: httpx.Request) -> httpx.Response:
        payload = handler(request)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(respond)


def test_openai_compatible_parses_and_sorts_models() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> dict:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return {
            "data": [
                {"id": "gpt-4o", "object": "model"},
                {"id": "gpt-4o", "object": "model"},
                {"id": "gpt-4o-mini", "object": "model"},
                {"id": "deepseek-chat", "object": "model"},
            ]
        }

    result = fetch_provider_models(
        "openai_compatible",
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        transport=_ok_payload(handler),
    )

    assert seen["url"] == "https://api.example.com/v1/models"
    assert seen["auth"] == "Bearer sk-test"
    assert result == [
        {"value": "deepseek-chat", "label": "deepseek-chat"},
        {"value": "gpt-4o", "label": "gpt-4o"},
        {"value": "gpt-4o-mini", "label": "gpt-4o-mini"},
    ]


def test_openai_compatible_default_base_url_when_empty() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> dict:
        seen_urls.append(str(request.url))
        return {"data": [{"id": "gpt-4o-mini"}]}

    result = fetch_provider_models(
        "openai", base_url="", api_key="k", transport=_ok_payload(handler)
    )

    assert seen_urls == ["https://api.openai.com/v1/models"]
    assert result == [{"value": "gpt-4o-mini", "label": "gpt-4o-mini"}]


def test_openai_compatible_no_auth_header_without_key() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> dict:
        seen_headers.update(dict(request.headers))
        return {"data": [{"id": "local-model"}]}

    fetch_provider_models(
        "openai_compatible", api_key="", transport=_ok_payload(handler)
    )

    assert "authorization" not in seen_headers


def test_anthropic_appends_v1_models_and_uses_display_name() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> dict:
        seen["url"] = str(request.url)
        seen["x-api-key"] = request.headers.get("x-api-key", "")
        seen["version"] = request.headers.get("anthropic-version", "")
        return {
            "data": [
                {"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"},
                {"id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5"},
            ]
        }

    result = fetch_provider_models(
        "anthropic",
        base_url="https://api.anthropic.com",
        api_key=_PROBE_VALUE,
        transport=_ok_payload(handler),
    )

    assert seen["url"] == "https://api.anthropic.com/v1/models"
    assert seen["x-api-key"] == _PROBE_VALUE
    assert seen["version"] == "2023-06-01"
    assert result == [
        {"value": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
        {"value": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5"},
    ]


def test_anthropic_base_url_ending_in_v1_uses_models_directly() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> dict:
        seen_urls.append(str(request.url))
        return {"data": []}

    fetch_provider_models(
        "anthropic",
        base_url="https://api.anthropic.com/v1",
        transport=_ok_payload(handler),
    )

    assert seen_urls == ["https://api.anthropic.com/v1/models"]


def test_ollama_strips_v1_and_parses_tags() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> dict:
        seen["url"] = str(request.url)
        return {
            "models": [
                {"name": "qwen2.5:7b", "model": "qwen2.5:7b"},
                {"name": "llama3.1:8b", "model": "llama3.1:8b"},
            ]
        }

    result = fetch_provider_models(
        "ollama",
        base_url="http://localhost:11434/v1",
        transport=_ok_payload(handler),
    )

    assert seen["url"] == "http://localhost:11434/api/tags"
    assert result == [
        {"value": "llama3.1:8b", "label": "llama3.1:8b"},
        {"value": "qwen2.5:7b", "label": "qwen2.5:7b"},
    ]


def test_401_raises_auth_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": {"message": "bad key"}})
    )

    with pytest.raises(ValueError, match="API key"):
        fetch_provider_models("openai_compatible", api_key="bad", transport=transport)


def test_404_raises_base_url_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, json={"error": {"message": "not found"}})
    )

    with pytest.raises(ValueError, match="base URL"):
        fetch_provider_models("anthropic", transport=transport)


def test_connect_error_raises_value_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)

    with pytest.raises(ValueError, match="cannot reach"):
        fetch_provider_models("ollama", transport=transport)


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        fetch_provider_models("weird_provider")


def test_malformed_payload_raises() -> None:
    def handler(request: httpx.Request) -> dict:
        return {"unexpected": True}

    with pytest.raises(ValueError, match="no model list"):
        fetch_provider_models("openai_compatible", transport=_ok_payload(handler))

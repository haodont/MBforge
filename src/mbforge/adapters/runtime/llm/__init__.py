"""Shared LLM factory — creates LangChain chat models from global settings.

Supports: openai, anthropic, ollama, openai_compatible.

Business LLM settings come from ``AppConfig.llm`` (the Settings UI persists it
to ``settings.json``). Explicit function arguments remain available for
callers that intentionally need a one-off override. Used by the pipeline
content-extraction steps (cloud molecule registration fallback) and the
readiness LLM probe.

This package also hosts the provider model-list probe
(:func:`fetch_provider_models`) and the LiteLLM mapping helpers, so the whole
"which providers / defaults / chat client" surface lives in one place.
"""

from __future__ import annotations

from typing import Any

from mbforge.adapters.runtime.llm.litellm import to_litellm_config, to_litellm_model
from mbforge.adapters.runtime.llm.provider_config import default_base_url, provider_kind
from mbforge.adapters.runtime.llm.provider_models import fetch_provider_models
from mbforge.foundation.config import load_global_config
from mbforge.foundation.logger import get_logger

__all__ = [
    "create_llm",
    "create_llm_from_settings",
    "fetch_provider_models",
    "to_litellm_config",
    "to_litellm_model",
]

logger = get_logger("mbforge.adapters.runtime.llm")


def _resolve_provider(arg: str, cfg_provider: str) -> str:
    return arg or cfg_provider or "openai_compatible"


def _resolve_api_key(arg: str, cfg_key: str) -> str:
    """Resolve an explicit API key or the persisted LLM setting."""
    return arg or cfg_key


def _resolve_base_url(arg: str, cfg_url: str) -> str:
    return arg or cfg_url


def _resolve_model(arg: str, cfg_model: str, default: str) -> str:
    return arg or cfg_model or default


def create_llm(
    provider: str = "",
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    **kwargs: Any,
) -> Any:
    """Create a LangChain chat model.

    Priority: explicit args > AppConfig.llm > defaults.
    """
    llm_cfg = load_global_config().llm
    provider = _resolve_provider(provider, llm_cfg.provider)
    kind = provider_kind(provider)  # raises ValueError for unknown providers

    temperature = kwargs.get("temperature", llm_cfg.temperature)
    max_tokens = kwargs.get("max_tokens", llm_cfg.max_tokens)
    request_timeout = kwargs.get("request_timeout", llm_cfg.request_timeout)

    if kind == "openai_compatible":
        api_key = _resolve_api_key(api_key, llm_cfg.api_key)
        if not api_key:
            raise ValueError(
                "api_key required for OpenAI-compatible provider (set via Settings UI)"
            )
        # Chat talks the OpenAI-compatible protocol on {base}/v1.
        base_url = _resolve_base_url(base_url, llm_cfg.base_url)
        if not base_url:
            base_url = default_base_url(provider)  # already includes /v1
        model = _resolve_model(model, llm_cfg.model, "gpt-3.5-turbo")

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=request_timeout,
        )

    elif kind == "ollama":
        # Ollama uses an OpenAI-compatible endpoint and does not require a real
        # API key. A non-empty placeholder avoids validation errors in the
        # LangChain OpenAI client while keeping the local provider keyless.
        base_url = _resolve_base_url(base_url, llm_cfg.base_url)
        if not base_url:
            base_url = "http://localhost:11434/v1"
        model = _resolve_model(model, llm_cfg.model, "llama3")
        api_key = _resolve_api_key(api_key, llm_cfg.api_key) or "ollama"

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=request_timeout,
        )

    elif kind == "anthropic":
        api_key = _resolve_api_key(api_key, llm_cfg.api_key)
        if not api_key:
            raise ValueError(
                "api_key required for Anthropic provider (set via Settings UI)"
            )
        model = _resolve_model(model, llm_cfg.model, "")
        if not model:
            raise ValueError(
                "model required for Anthropic provider (set via Settings UI)"
            )
        base_url = _resolve_base_url(base_url, llm_cfg.base_url)

        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "max_tokens": max_tokens,
            "timeout": request_timeout,
        }
        if base_url:
            kwargs["base_url"] = base_url
        if "thinking" not in model.lower():
            kwargs["temperature"] = temperature
        return ChatAnthropic(**kwargs)

    raise ValueError(f"Unknown LLM provider: {provider}")


def create_llm_from_settings() -> Any:
    """Create an LLM from the persisted global settings."""
    return create_llm()

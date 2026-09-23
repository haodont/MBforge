"""LiteLLM model-string/config mapping.

Pure functions over :class:`~mbforge.foundation.config.LLMConfig` — no I/O, no
environment mutation. Exposed here so future LiteLLM callers share one
mapping instead of re-deriving model strings ad hoc.
"""

from __future__ import annotations

from typing import Any

from mbforge.foundation.config import LLMConfig


def to_litellm_model(cfg: LLMConfig) -> str:
    """Map an :class:`LLMConfig` to a LiteLLM model string."""
    model = cfg.model
    known_prefixes = {
        "openai",
        "anthropic",
        "ollama",
        "gemini",
        "groq",
        "bedrock",
        "azure",
        "deepseek",
        "together",
        "mistral",
    }
    if "/" in model and model.split("/", 1)[0] in known_prefixes:
        return model
    if (cfg.provider or "").lower().strip() == "ollama":
        return f"ollama/{model}"
    return f"openai/{model}"


def to_litellm_config(cfg: LLMConfig) -> dict[str, Any]:
    """Build explicit LiteLLM call parameters without mutating environment state."""
    result: dict[str, Any] = {
        "model": to_litellm_model(cfg),
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    if cfg.api_key:
        result["api_key"] = cfg.api_key
    if cfg.base_url:
        result["api_base"] = cfg.base_url
    return result

"""Provider classification and defaults — the single source of truth.

Consumed by the chat-model factory (:mod:`mbforge.infra.llm`), the
model-list probe (:mod:`mbforge.infra.llm.provider_models`), the readiness
diagnostics (``services/system/readiness.py``) and activity extraction
(``pipeline/activity/extraction.py``). Keeping the default base URLs and
the "which providers are OpenAI-compatible" tuple here removes the four
independent copies that used to drift apart.

``default_base_url`` returns the **chat endpoint** default (with ``/v1``) for
providers that chat over the OpenAI-compatible protocol. Anthropic has no
entry here — it needs no base URL override to reach the official endpoint,
and callers special-case it. The model-list probe appends its own
provider-specific paths on top of these defaults and strips the trailing
``/v1`` when a provider's native API differs (Ollama ``/api/tags``).
"""

from __future__ import annotations

# Providers that speak the OpenAI chat-completions protocol (Bearer key on
# ``{base}/v1``). Both the factory and the probe treat them the same way.
_OPENAI_COMPATIBLE: tuple[str, ...] = ("openai_compatible", "openai", "deepseek")

# Chat-endpoint default base URLs, used when the setting is left empty.
# Openai-compatible providers chat on ``{base}/v1``. ``anthropic`` is
# intentionally absent (no override needed for the official endpoint);
# ``ollama`` chat defaults are handled in the factory.
DEFAULT_BASE_URLS: dict[str, str] = {
    "openai_compatible": "https://api.openai.com/v1",
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
}


def provider_kind(provider: str) -> str:
    """Classify a provider: ``openai_compatible``, ``anthropic`` or ``ollama``.

    Unknown providers raise ``ValueError`` so callers fail fast instead of
    silently constructing a client for a typo'd provider name.
    """
    key = (provider or "").strip().lower()
    if key in _OPENAI_COMPATIBLE:
        return "openai_compatible"
    if key == "anthropic":
        return "anthropic"
    if key == "ollama":
        return "ollama"
    raise ValueError(f"unsupported LLM provider: {provider}")


def default_base_url(provider: str) -> str:
    """Return the default chat base URL for ``provider`` (empty if unlisted)."""
    key = (provider or "").strip().lower()
    return DEFAULT_BASE_URLS.get(key, "")

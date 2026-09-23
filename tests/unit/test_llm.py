from __future__ import annotations

from types import SimpleNamespace

import pytest

from mbforge.adapters.runtime import llm
from mbforge.adapters.runtime.llm import to_litellm_config, to_litellm_model
from mbforge.foundation.config import LLMConfig


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("ollama", "llama3", "ollama/llama3"),
        ("openai_compatible", "custom", "openai/custom"),
    ],
)
def test_to_litellm_model_supports_provider_prefixes(
    provider: str, model: str, expected: str
) -> None:
    cfg = LLMConfig(provider=provider, model=model, base_url="https://example.test/v1")
    assert to_litellm_model(cfg) == expected
    assert to_litellm_config(cfg)["api_base"] == "https://example.test/v1"


def test_create_llm_does_not_fall_back_to_environment_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An obsolete environment key must not bypass an empty Settings UI value."""
    monkeypatch.setenv("MBFORGE_LLM_API_KEY", "legacy-environment-key")
    monkeypatch.setattr(
        llm,
        "load_global_config",
        lambda: SimpleNamespace(llm=LLMConfig(api_key="")),
    )

    with pytest.raises(ValueError, match="set via Settings UI"):
        llm.create_llm()


def test_create_llm_anthropic_passes_custom_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured custom base URL must reach ChatAnthropic, not be dropped."""
    import sys
    from types import ModuleType

    captured: dict = {}

    class _FakeChatAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake = ModuleType("langchain_anthropic")
    fake.ChatAnthropic = _FakeChatAnthropic
    monkeypatch.setitem(sys.modules, "langchain_anthropic", fake)

    monkeypatch.setattr(
        llm,
        "load_global_config",
        lambda: SimpleNamespace(
            llm=LLMConfig(
                provider="anthropic",
                model="claude-3-5-sonnet-latest",
                api_key="test-key",
                base_url="",
            )
        ),
    )

    llm.create_llm(provider="anthropic", base_url="https://anthropic.example.test")
    assert captured["base_url"] == "https://anthropic.example.test"

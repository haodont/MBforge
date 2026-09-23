"""Tests for mbforge.foundation.config schema and helpers."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from mbforge.foundation.config import (
    AppConfig,
    IngestConfig,
    LLMConfig,
    MoldetConfig,
    PdfParseConfig,
    reset_config_cache,
    update_settings,
)
from mbforge.interfaces.http.system.settings import _redact_secrets

# Neutral stand-ins for secret-shaped literals: the tests only assert that
# stored values round-trip, so the stubs stay free of credential shapes.
_DISK_VALUE = "disk-value-roundtrip"
_TYPED_VALUE = "typed-value-roundtrip"


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    """Clear the config lru_cache before each test."""
    reset_config_cache()
    yield
    reset_config_cache()


class TestDefaultValues:
    """Default values must match the historical hard-coded fallbacks."""

    def test_llm_defaults(self) -> None:
        cfg = LLMConfig()
        assert cfg.provider == "openai_compatible"
        assert cfg.model == "gpt-4o-mini"
        assert cfg.temperature == pytest.approx(0.7)
        assert cfg.max_tokens == 4096
        assert cfg.top_p == pytest.approx(1.0)
        assert cfg.request_timeout == 60
        assert cfg.molecule_tool_enabled is False
        assert cfg.molecule_tool_max_chars == 16000

    def test_moldet_defaults(self) -> None:
        cfg = MoldetConfig()
        assert cfg.device == "auto"
        assert cfg.auto_moldet_on_import is True
        assert cfg.detection_dpi == pytest.approx(200.0)
        assert cfg.detection_batch_size == 0
        assert cfg.text_page_char_threshold == 500
        assert cfg.max_pages_per_doc is None

    def test_ingest_defaults(self) -> None:
        cfg = IngestConfig()
        assert cfg.auto_enqueue_on_import is True
        assert cfg.default_priority == 0
        assert cfg.max_retries == 1

    def test_pdf_parse_defaults(self) -> None:
        cfg = PdfParseConfig()
        assert cfg.chunk_size == 1000
        assert cfg.chunk_overlap == 200


class TestValidation:
    """Invalid types must raise ValidationError."""

    def test_invalid_temperature_type(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfig(temperature="hot")

    def test_molecule_tool_settings_reject_invalid_ranges(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfig(molecule_tool_max_chars=999)
        with pytest.raises(ValidationError):
            LLMConfig(molecule_tool_max_chars=100001)

    def test_invalid_detection_dpi_type(self) -> None:
        with pytest.raises(ValidationError):
            MoldetConfig(detection_dpi="high")

    def test_app_config_ignores_environment_variables(self, monkeypatch) -> None:
        """Business settings must come from settings.json, never MBFORGE_* env vars."""
        monkeypatch.setenv("MBFORGE_THEME", "light")

        assert AppConfig().theme == "dark"


class TestDictDeserialization:
    """Legacy dict-shaped settings.json must deserialize correctly."""

    def test_app_config_from_nested_dict(self) -> None:
        data: dict[str, Any] = {
            "layout": {
                "conf_threshold": 0.55,
            },
            "moldet": {
                "detection_dpi": 300.0,
                "detection_batch_size": 2,
            },
        }
        cfg = AppConfig.model_validate(data)
        assert cfg.layout.conf_threshold == pytest.approx(0.55)
        assert cfg.moldet.detection_dpi == pytest.approx(300.0)
        assert cfg.moldet.detection_batch_size == 2

    def test_update_settings_deep_merge(self, monkeypatch, tmp_path) -> None:
        from mbforge.foundation import config

        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(config, "_SETTINGS_PATH", settings_path)
        monkeypatch.setattr(config, "GLOBAL_APP_DIR", tmp_path)

        initial = AppConfig()
        initial.library_root = str(tmp_path)
        config.save_global_config(initial)

        new_cfg = update_settings(
            {
                "layout": {"conf_threshold": 0.55},
                "moldet": {"device": "cpu"},
            }
        )
        assert new_cfg.layout.conf_threshold == pytest.approx(0.55)
        assert new_cfg.moldet.device == "cpu"
        # Other defaults preserved
        assert new_cfg.layout.read_text is True
        assert new_cfg.moldet.detection_dpi == pytest.approx(200.0)

    def test_load_normalizes_and_persists_library_root(
        self, monkeypatch, tmp_path
    ) -> None:
        from mbforge.foundation import config

        settings_path = tmp_path / "settings.json"
        raw_root = tmp_path / "library" / ".." / "library"
        settings_path.write_text(
            json.dumps({"library_root": str(raw_root)}), encoding="utf-8"
        )
        monkeypatch.setattr(config, "_SETTINGS_PATH", settings_path)
        monkeypatch.setattr(config, "GLOBAL_APP_DIR", tmp_path)

        loaded = config.load_global_config()
        expected = str((tmp_path / "library").resolve())

        assert loaded.library_root == expected
        persisted = json.loads(settings_path.read_text(encoding="utf-8"))
        assert persisted["library_root"] == expected


class TestSecretRedaction:
    """GET /api/v1/settings must not leak credentials."""

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("api_key", "secret"),
            ("secret_token", "secret"),
            ("hf_key", "secret"),
            ("password", "secret"),
            ("auth_token", "secret"),
        ],
    )
    def test_secret_keys_redacted(self, key: str, value: str) -> None:
        assert _redact_secrets({key: value}) == {key: "***"}

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("keyword", "secret"),
            ("monkey", "secret"),
            ("secretly", "secret"),
            ("tokens", "secret"),
            ("model", "secret"),
            ("host", "secret"),
        ],
    )
    def test_non_secret_keys_preserved(self, key: str, value: str) -> None:
        assert _redact_secrets({key: value}) == {key: value}

    def test_nested_redaction(self) -> None:
        data = {
            "llm": {"api_key": "ak", "model": "m"},
            "vlm": {"api_key": "vk"},
        }
        redacted = _redact_secrets(data)
        assert redacted["llm"]["api_key"] == "***"
        assert redacted["llm"]["model"] == "m"
        assert redacted["vlm"]["api_key"] == "***"

    def test_redacted_roundtrip_preserves_real_secret(
        self, monkeypatch, tmp_path
    ) -> None:
        """Boot a config with a real api_key, simulate the redacted GET path
        returning '***', then PUT that redacted payload back — the real
        secret on disk must survive (B1 regression)."""
        from mbforge.foundation import config

        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(config, "_SETTINGS_PATH", settings_path)
        monkeypatch.setattr(config, "GLOBAL_APP_DIR", tmp_path)

        # Seed with a real key on disk.
        initial = AppConfig()
        initial.library_root = str(tmp_path)
        initial = initial.model_copy(
            update={"llm": initial.llm.model_copy(update={"api_key": _DISK_VALUE})}
        )
        config.save_global_config(initial)

        # Roundtrip a redacted payload (mimicking what the UI sends after
        # reading the GET response + not changing the field).
        new_cfg = update_settings(
            {
                "llm": {"api_key": "***", "model": "gpt-4o"},
                "vlm": {"api_key": "***"},
            }
        )
        assert new_cfg.llm.api_key == _DISK_VALUE, (
            f"*** marker must preserve the disk value, but got {new_cfg.llm.api_key!r}"
        )
        assert new_cfg.llm.model == "gpt-4o"
        # The VLM key was empty on disk → *** marker preserves that empty state
        assert new_cfg.vlm.api_key == ""
        # Real PUT (e.g. user typing a new key, or empty to clear) still works.
        cleared = update_settings({"llm": {"api_key": ""}})
        assert cleared.llm.api_key == ""

        cleared2 = update_settings({"llm": {"api_key": _TYPED_VALUE}})
        assert cleared2.llm.api_key == _TYPED_VALUE


def test_app_config_ignores_retired_project_settings() -> None:
    """Existing settings.json files must remain loadable after the cleanup."""
    cfg = AppConfig.model_validate(
        {
            "auto_open_project": True,
            "recent_projects": [{"root": "/tmp/library", "name": "Old library"}],
        }
    )

    assert "auto_open_project" not in cfg.model_dump()
    assert "recent_projects" not in cfg.model_dump()

    unknown = AppConfig(unknown_field="value")
    assert "unknown_field" not in unknown.model_dump()

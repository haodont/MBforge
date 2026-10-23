"""Tests for mbforge.foundation.config schema and helpers.

Covers ``AppConfig`` (defaults, validation, dict deserialization),
``update_settings`` / ``load_global_config`` persistence + normalization, the
retired-settings compatibility window, and the ``_redact_secrets`` credential
boundary used by ``GET /api/v1/settings``.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mbforge.api.http.system.settings import _redact_secrets
from mbforge.foundation.config import (
    AppConfig,
    IngestConfig,
    MoldetConfig,
    PdfParseConfig,
    reset_config_cache,
    update_settings,
)

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


def test_sub_config_defaults_match_historical_fallbacks() -> None:
    """The sub-config defaults must match the historical hard-coded fallbacks."""
    moldet = MoldetConfig()
    assert moldet.device == "auto"
    assert moldet.auto_moldet_on_import is True
    assert moldet.detection_dpi == pytest.approx(200.0)
    assert moldet.detection_batch_size == 0
    assert moldet.text_page_char_threshold == 500
    assert moldet.max_pages_per_doc is None

    ingest = IngestConfig()
    assert ingest.auto_enqueue_on_import is True
    assert ingest.default_priority == 0
    assert ingest.max_retries == 1

    pdf_parse = PdfParseConfig()
    assert pdf_parse.chunk_size == 1000
    assert pdf_parse.chunk_overlap == 200


def test_app_config_rejects_invalid_field_types() -> None:
    """A wrong-typed business setting must raise ``ValidationError``."""
    with pytest.raises(ValidationError):
        MoldetConfig(detection_dpi="high")


def test_app_config_defaults_ignore_environment_variables(monkeypatch) -> None:
    """Business settings must come from settings.json, never MBFORGE_* env vars."""
    monkeypatch.setenv("MBFORGE_THEME", "light")

    assert AppConfig().theme == "dark"


def test_settings_dict_round_trip_deep_merges_and_normalizes(
    monkeypatch, tmp_path
) -> None:
    """Nested dicts override only the named fields and settings.json persists
    normalized values (a non-normalized ``library_root`` is resolved on load)."""
    from mbforge.foundation import config

    # Nested-dict deserialization: untouched fields keep their defaults.
    nested = AppConfig.model_validate(
        {
            "layout": {"conf_threshold": 0.55},
            "moldet": {"detection_dpi": 300.0, "detection_batch_size": 2},
        }
    )
    assert nested.layout.conf_threshold == pytest.approx(0.55)
    assert nested.moldet.detection_dpi == pytest.approx(300.0)
    assert nested.moldet.detection_batch_size == 2
    assert nested.layout.cross_model is True
    assert nested.moldet.device == "auto"

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
    assert new_cfg.layout.cross_model is True
    assert new_cfg.moldet.detection_dpi == pytest.approx(200.0)

    # A non-normalized library_root is normalized and written back on load.
    raw_root = tmp_path / "library" / ".." / "library"
    settings_path.write_text(
        json.dumps({"library_root": str(raw_root)}), encoding="utf-8"
    )
    loaded = config.load_global_config()
    expected = str((tmp_path / "library").resolve())
    assert loaded.library_root == expected
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["library_root"] == expected


def test_redact_secrets_masks_only_credential_keys() -> None:
    """GET /api/v1/settings must not leak credentials — and nothing else.

    Secret-shaped key names (and their nested occurrences) become ``***``;
    lookalike keys keep their value.
    """
    for key in ("api_key", "secret_token", "hf_key", "password", "auth_token"):
        assert _redact_secrets({key: "secret"}) == {key: "***"}, key
    for key in ("keyword", "monkey", "secretly", "tokens", "model", "host"):
        assert _redact_secrets({key: "secret"}) == {key: "secret"}, key

    data = {
        "llm": {"api_key": "ak", "model": "m"},
        "vlm": {"api_key": "vk"},
    }
    redacted = _redact_secrets(data)
    assert redacted["llm"]["api_key"] == "***"
    assert redacted["llm"]["model"] == "m"
    assert redacted["vlm"]["api_key"] == "***"


def test_redacted_roundtrip_preserves_real_secret(monkeypatch, tmp_path) -> None:
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
    initial.web_search.enabled = True
    initial.web_search.api_key = _DISK_VALUE
    initial = initial.model_copy(update={"llm": {"api_key": _DISK_VALUE}})
    config.save_global_config(initial)

    # Roundtrip a redacted payload (mimicking what the UI sends after
    # reading the GET response + not changing the field).
    new_cfg = update_settings(
        {
            "llm": {"api_key": "***", "model": "gpt-4o"},
            "vlm": {"api_key": "***"},
            "web_search": {"enabled": False, "api_key": "***"},
        }
    )
    assert new_cfg.llm["api_key"] == _DISK_VALUE, (
        f"*** marker must preserve the disk value, but got {new_cfg.llm['api_key']!r}"
    )
    assert new_cfg.llm["model"] == "gpt-4o"
    # The VLM key was empty on disk → *** marker preserves that empty state
    assert new_cfg.vlm.api_key == ""
    assert new_cfg.web_search.api_key == _DISK_VALUE
    assert not new_cfg.web_search.enabled
    assert _redact_secrets(new_cfg.model_dump())["web_search"]["api_key"] == "***"
    # Real PUT (e.g. user typing a new key, or empty to clear) still works.
    cleared = update_settings({"llm": {"api_key": ""}})
    assert cleared.llm["api_key"] == ""

    cleared2 = update_settings({"llm": {"api_key": _TYPED_VALUE}})
    assert cleared2.llm["api_key"] == _TYPED_VALUE


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

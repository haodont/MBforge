"""Model inference settings must come from persisted application settings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mbforge.adapters.inference.moldet_v2_ft import MolDetv2Detector
from mbforge.foundation.config import AppConfig, MoldetConfig


def test_moldet_device_ignores_legacy_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("MBFORGE_DEVICE", "cuda:99")
    config = AppConfig(moldet=MoldetConfig(device="cpu"))

    with (
        patch(
            "mbforge.adapters.inference.moldet_v2_ft._has_ultralytics",
            return_value=True,
        ),
        patch.object(MolDetv2Detector, "_load_model"),
        patch(
            "mbforge.adapters.inference.moldet_v2_ft.load_global_config",
            return_value=config,
        ),
    ):
        detector = MolDetv2Detector(model_path=Path("weights.pt"))

    assert detector.device == "cpu"

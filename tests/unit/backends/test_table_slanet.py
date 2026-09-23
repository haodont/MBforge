"""SLANet-1M adapter degradation contract.

The recognizer is best-effort enrichment: without weights it must report a
clear error state, and ``predict_table`` must return an empty string instead
of raising. No test here downloads weights or touches the network.
"""

from __future__ import annotations

import numpy as np

from mbforge.adapters.inference import table_slanet


def test_predict_table_returns_empty_when_model_unavailable(monkeypatch) -> None:
    """Unavailable model degrades to ``""`` without raising or downloading."""
    monkeypatch.setattr(table_slanet, "_SESSION", None)
    monkeypatch.setattr(table_slanet, "_AVAILABLE", False)
    monkeypatch.setattr(table_slanet, "_ERROR", "not loaded")
    monkeypatch.setattr(table_slanet, "load", lambda device=None: None)

    image = np.zeros((40, 80, 3), dtype=np.uint8)
    assert table_slanet.predict_table(image) == ""


def test_load_reports_missing_weights_without_download(monkeypatch) -> None:
    """Missing weights set a clear error state; load never raises."""
    monkeypatch.setattr(table_slanet, "_SESSION", None)
    monkeypatch.setattr(table_slanet, "_AVAILABLE", False)
    monkeypatch.setattr(table_slanet, "_ERROR", "")
    monkeypatch.setattr(
        "mbforge.adapters.runtime.resource_manager.ResourceManager.get_slanet_path",
        lambda: None,
    )
    monkeypatch.setattr(
        "mbforge.adapters.runtime.resource_manager.ResourceManager.ensure",
        lambda resource_id: None,
    )

    table_slanet.load()

    assert table_slanet._SESSION is None
    assert table_slanet._AVAILABLE is False
    assert "not found" in table_slanet._ERROR

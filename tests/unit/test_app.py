"""Tests for FastAPI app wiring (disconnect filter, CORS origins)."""

from __future__ import annotations


def test_app_wiring_helpers(monkeypatch) -> None:
    """Expected client resets are limited to WinError 10054 and dev CORS
    origins follow the configured frontend host/port."""
    from mbforge.server.app import (
        _development_frontend_origins,
        _is_expected_client_disconnect,
    )

    assert _is_expected_client_disconnect({"exception": ConnectionResetError(10054)})
    assert not _is_expected_client_disconnect({"exception": ConnectionResetError(111)})
    assert not _is_expected_client_disconnect({"exception": RuntimeError("reset")})

    monkeypatch.setenv("MBFORGE_FRONTEND_HOST", "127.0.0.1")
    monkeypatch.setenv("MBFORGE_FRONTEND_PORT", "25173")

    assert _development_frontend_origins() == [
        "http://127.0.0.1:25173",
        "http://localhost:25173",
    ]

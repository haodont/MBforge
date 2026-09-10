"""Tests for FastAPI app wiring (disconnect filter, CORS origins)."""

from __future__ import annotations


def test_expected_client_disconnect_is_limited_to_winerror_10054() -> None:
    from mbforge.app import _is_expected_client_disconnect

    assert _is_expected_client_disconnect({"exception": ConnectionResetError(10054)})
    assert not _is_expected_client_disconnect({"exception": ConnectionResetError(111)})
    assert not _is_expected_client_disconnect({"exception": RuntimeError("reset")})


def test_development_frontend_origins_follow_configured_port(monkeypatch) -> None:
    from mbforge.app import _development_frontend_origins

    monkeypatch.setenv("MBFORGE_FRONTEND_HOST", "127.0.0.1")
    monkeypatch.setenv("MBFORGE_FRONTEND_PORT", "25173")

    assert _development_frontend_origins() == [
        "http://127.0.0.1:25173",
        "http://localhost:25173",
    ]

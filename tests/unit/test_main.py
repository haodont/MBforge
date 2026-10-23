from __future__ import annotations

from unittest.mock import patch

import pytest


def test_main_uvicorn_run_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI flags + MBFORGE_PORT resolve into the uvicorn.run kwargs."""
    from mbforge import __main__

    cases = [
        (["--reload", "--no-browser"], None, 18792, True),
        (["--no-browser"], "28792", 28792, False),
    ]
    for argv, env_port, expected_port, expected_reload in cases:
        if env_port is None:
            monkeypatch.delenv("MBFORGE_PORT", raising=False)
        else:
            monkeypatch.setenv("MBFORGE_PORT", env_port)

        with (
            patch.object(__main__, "_port_in_use", return_value=False),
            patch("uvicorn.run") as run,
        ):
            __main__.main(argv)

        kwargs = run.call_args.kwargs
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == expected_port, argv
        assert kwargs["reload"] is expected_reload, argv
        assert kwargs["log_level"] == "warning"
        assert kwargs["reload_dirs"] == (["src"] if expected_reload else None)

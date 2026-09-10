from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    ("argv", "env_port", "expected_port", "expected_reload"),
    [
        (["--reload", "--no-browser"], None, 18792, True),
        (["--no-browser"], "28792", 28792, False),
    ],
)
def test_main_uvicorn_run_options(
    argv: list[str],
    env_port: str | None,
    expected_port: int,
    expected_reload: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mbforge import __main__

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
    assert kwargs["port"] == expected_port
    assert kwargs["reload"] is expected_reload
    assert kwargs["log_level"] == "warning"
    assert kwargs["reload_dirs"] == (["src"] if expected_reload else None)

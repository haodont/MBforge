"""Verify that public application version consumers stay synchronized."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from mbforge import __version__
from mbforge.app import create_app

ROOT = Path(__file__).parents[2]


def test_version_sources_are_consistent() -> None:
    """The package, frontend, and API must advertise one release version."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        backend_version = tomllib.load(handle)["project"]["version"]
    with (ROOT / "frontend" / "package.json").open(encoding="utf-8") as handle:
        frontend_version = json.load(handle)["version"]

    assert frontend_version == backend_version
    assert __version__ == backend_version
    assert create_app().version == backend_version

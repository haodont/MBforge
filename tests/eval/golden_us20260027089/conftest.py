"""Golden reference loader for the US20260027089A1 evaluation suite.

The golden reference JSON lives at
``test_data/golden/US20260027089A1/reference.json``. This fixture exposes it
as a session-scoped dict so individual eval modules can index into the
``activity_rows``, ``markush_anchors``, and ``concrete_molecule_anchors``
sections without re-parsing the file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = (
    Path(__file__).resolve().parents[3] / "test_data" / "golden" / "US20260027089A1"
)
REFERENCE_PATH = GOLDEN_DIR / "reference.json"


@pytest.fixture(scope="session")
def golden_reference() -> dict[str, Any]:
    """Return the parsed golden reference dict."""
    if not REFERENCE_PATH.exists():
        pytest.skip(f"Golden reference missing at {REFERENCE_PATH}")
    with REFERENCE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def golden_root() -> Path:
    """Return the directory holding the golden reference and artifacts."""
    if not GOLDEN_DIR.exists():
        pytest.skip(f"Golden directory missing at {GOLDEN_DIR}")
    return GOLDEN_DIR

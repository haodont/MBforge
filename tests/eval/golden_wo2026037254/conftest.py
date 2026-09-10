"""Golden reference loader for the WO2026037254A1 evaluation suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = (
    Path(__file__).resolve().parents[3] / "test_data" / "golden" / "WO2026037254A1"
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

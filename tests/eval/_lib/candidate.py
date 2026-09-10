"""Candidate JSON loader shared by every golden evaluator."""

from __future__ import annotations

import json
from pathlib import Path


def load_candidate(path: Path) -> dict:
    """Read a candidate JSON dump and return it verbatim."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)

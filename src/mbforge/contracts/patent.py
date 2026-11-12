"""Patent-analysis contracts: the committed publication status.

The Patent stage is deterministic; these literals describe how one analysis
attempt ended and how the published facts were produced. Sections, entries,
structures and labels stay deterministic; no model draft is part of this
contract.
"""

from __future__ import annotations

from typing import Literal

#: Terminal outcome of one analysis attempt.
AnalysisStatus = Literal["disabled", "succeeded", "partial", "fallback"]

#: How the published facts were produced. The live pipeline is deterministic.
ExtractionMode = Literal["deterministic", "hybrid"]

__all__ = [
    "AnalysisStatus",
    "ExtractionMode",
]

"""Re-export shim for the stage result contract.

The canonical home is :mod:`mbforge.core.stage_result`; this module keeps the
historical ``mbforge.pipeline.stage_result`` import path working (see
TODO/services-layer-plan.md A1). New code should import from
``mbforge.core.stage_result``.
"""

from __future__ import annotations

from ..core.stage_result import PipelineErrorCode, StageResult

__all__ = ["PipelineErrorCode", "StageResult"]

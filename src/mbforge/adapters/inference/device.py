"""Backend device capability queries.

Device/GPU probing lives here (backends own model placement), not in
utils — device/GPU helpers moved here from the utils package resolve the
utils→backends dependency inversion (TODO/services-layer-plan.md ①/A4).
"""

from __future__ import annotations

import os

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

_gpu_cached: bool | None = None


def is_gpu_available() -> bool:
    """Check if NVIDIA GPU with CUDA is available (cached; env-overridable)."""
    global _gpu_cached
    if _gpu_cached is not None:
        return _gpu_cached
    if os.environ.get("MBFORGE_FORCE_CPU", "").strip() == "1":
        _gpu_cached = False
        return False
    try:
        import torch  # noqa: F401

        available = torch.cuda.is_available()
    except ImportError:
        available = False
    _gpu_cached = available
    return available

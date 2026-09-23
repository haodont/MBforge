"""Local model lifecycle management (infra layer).

Owns the in-process model singletons: loaded-state reporting, unloading
(freeing GPU memory without deleting weight files) and smoke-test
inference. HTTP endpoints live in ``interfaces/http/system/models.py``; the
render endpoint stays there until the M2 chem 汇合点
(the model lifecycle boundary).

The public names (:func:`loaded`, :func:`clear`, :func:`run_test`) are
re-exported from the package ``__init__``; the underlying helpers stay
underscore-prefixed so pytest never collects them.
"""

from __future__ import annotations

import gc
from typing import Any


def loaded() -> dict[str, Any]:
    """Report loaded model singletons and current process memory."""
    import os

    import psutil

    process_memory_mb = round(
        psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 1
    )

    from mbforge.adapters.inference import moldet_v2_ft, molparser

    return {
        "models": [
            {"id": "moldet", "loaded": moldet_v2_ft._detector_singleton is not None},
            {"id": "molparser", "loaded": molparser._MODEL is not None},
        ],
        "process_memory_mb": process_memory_mb,
    }


def clear(model_id: str | None = None) -> dict[str, Any]:
    """Unload selected or all in-process models without deleting weight files."""
    from mbforge.foundation.logger import get_logger

    logger = get_logger(__name__)
    if model_id not in (None, "moldet", "molparser"):
        return {"success": False, "error": f"Unknown model: {model_id}"}

    if model_id in (None, "moldet"):
        from mbforge.adapters.inference import moldet_v2_ft

        moldet_v2_ft.unload()
    if model_id in (None, "molparser"):
        from mbforge.adapters.inference import molparser

        molparser.unload()

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        # torch is optional (CPU-only installs) — CUDA cache clearing is a no-op.
        logger.debug("torch not importable, skipping CUDA cache clear")
    return {"success": True, **loaded()}


def run_test(model_id: str, subpath: str | None = None) -> dict[str, Any]:
    """Test a model by loading and running inference (sync)."""
    import time

    from mbforge.foundation.logger import get_logger

    logger = get_logger(__name__)
    start = time.perf_counter()
    try:
        if model_id == "moldet":
            from mbforge.adapters.inference.moldet_v2_ft import MolDetv2Detector

            detector = MolDetv2Detector()
            if not detector.is_available():
                return {"ok": False, "error": "Model not loaded", "duration_ms": 0}
            import numpy as np

            _ = detector.detect(np.zeros((960, 960, 3), dtype=np.uint8))
        elif model_id == "molparser":
            from mbforge.adapters.inference.molparser import load as load_molparser

            load_molparser()
        else:
            return {
                "ok": False,
                "error": f"Unknown model: {model_id}",
                "duration_ms": 0,
            }

        duration_ms = int((time.perf_counter() - start) * 1000)
        return {"ok": True, "error": "", "duration_ms": duration_ms}
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.error("Model test failed for %s: %s", model_id, e)
        return {"ok": False, "error": str(e), "duration_ms": duration_ms}

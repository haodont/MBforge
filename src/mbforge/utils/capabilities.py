"""Optional-dependency capability probe for the MBForge runtime.

Probes which heavyweight, optional model dependencies are importable and
whether CUDA is available. This keeps API startup independent of model/GPU
availability: the web server always boots, and only features backed by a
missing package degrade — surfaced by an explicit warning instead of a
silent failure deep inside a request handler.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from .logger import get_logger

logger = get_logger(__name__)

# (module name, display label) pairs for the heavyweight optional groups
# (pyproject `local-models` / `gpu` extras). A module being importable says
# nothing about model weights, which ResourceManager reports separately.
_OPTIONAL_MODULES: tuple[tuple[str, str], ...] = (
    ("torch", "torch"),
    ("transformers", "transformers"),
    ("ultralytics", "ultralytics"),
    ("timm", "timm"),
    ("scipy", "scipy"),
    ("sklearn", "scikit-learn"),
    ("modelscope", "modelscope"),
    ("molparser", "molparser"),
    ("cairosvg", "cairosvg"),
)


@dataclass(frozen=True)
class CapabilityProbe:
    """Importability report for the optional dependency groups."""

    available: tuple[str, ...]
    missing: tuple[str, ...]
    cuda_available: bool


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def probe() -> CapabilityProbe:
    """Probe the optional heavy dependencies and CUDA availability."""
    available: list[str] = []
    missing: list[str] = []
    for module_name, label in _OPTIONAL_MODULES:
        (available if _module_available(module_name) else missing).append(label)

    cuda_available = False
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False
    return CapabilityProbe(
        available=tuple(sorted(available)),
        missing=tuple(sorted(missing)),
        cuda_available=cuda_available,
    )


def log_capability_summary() -> CapabilityProbe:
    """Probe, log, and return a capability report.

    Missing optional modules are logged at warning level so startup visibly
    surfaces the features that will be unavailable; otherwise it is INFO.
    Never raises — a failed probe must not prevent the API from booting.
    """
    try:
        report = probe()
    except Exception as e:
        logger.warning("Capability probe failed: %s", e)
        return CapabilityProbe(available=(), missing=(), cuda_available=False)

    parts = [
        "CUDA available" if report.cuda_available else "CUDA unavailable (CPU mode)"
    ]
    if report.available:
        parts.append("optional modules: " + ", ".join(report.available))
    if report.missing:
        parts.append("missing optional modules: " + ", ".join(report.missing))
    if report.missing:
        logger.warning("Capabilities: %s", "; ".join(parts))
    else:
        logger.info("Capabilities: %s", "; ".join(parts))
    return report

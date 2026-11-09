"""Agent-callable capability registry."""

from . import read as _read  # noqa: F401 — registers read capabilities
from .registry import (
    Capability,
    CapabilityContext,
    CapabilityMode,
    CapabilityResult,
    all_capabilities,
    get_capability,
    invoke,
    register,
)

__all__ = [
    "Capability",
    "CapabilityContext",
    "CapabilityMode",
    "CapabilityResult",
    "all_capabilities",
    "get_capability",
    "invoke",
    "register",
]

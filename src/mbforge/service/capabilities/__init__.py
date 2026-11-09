"""Agent-callable capability registry."""

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

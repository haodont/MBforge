"""Best-effort runtime readiness logging."""

from __future__ import annotations

from mbforge.foundation.capabilities import log_capability_summary
from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)


def check_environment() -> None:
    """Log optional dependency and model availability without blocking startup."""
    log_capability_summary()
    try:
        from mbforge.adapters.runtime.resource_manager import ResourceManager

        report = ResourceManager.check_all()
        logger.info("Environment: %s", report.summary)
        for resource in report.resources:
            icon = "✓" if resource.status.value == "ready" else "✗"
            logger.info("  %s %s: %s", icon, resource.name, resource.status.value)
    except Exception as exc:  # noqa: BLE001 - readiness must remain best effort
        logger.warning("Environment check failed: %s", exc)


__all__ = ["check_environment"]

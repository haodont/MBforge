"""Environment readiness checks.

This module lives in ``core`` (not ``utils``) because validating available
resources requires the higher-level ``ResourceManager``.
"""

from __future__ import annotations

from ..utils.logger import get_logger

logger = get_logger(__name__)


def check_environment() -> None:
    """检查环境资源状态（共享逻辑，供 app.py 和 server.py 调用）。"""
    from ..utils.capabilities import log_capability_summary

    log_capability_summary()
    try:
        from .resource_manager import ResourceManager

        report = ResourceManager.check_all()
        logger.info("Environment: %s", report.summary)
        for r in report.resources:
            icon = "✓" if r.status.value == "ready" else "✗"
            logger.info("  %s %s: %s", icon, r.name, r.status.value)
    except Exception as e:
        logger.warning("Environment check failed: %s", e)

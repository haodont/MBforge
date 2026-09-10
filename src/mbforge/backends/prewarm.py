"""Optional background pre-warming for heavyweight local models.

Called from the application lifespan when ``MBFORGE_PREWARM_MODELS=1``.
Loads the configured local backends (MolDetv2, MolParser-Mobile) in a worker
thread so startup stays fast; failures are logged but never prevent the
server from accepting requests.
"""

from __future__ import annotations

from collections.abc import Callable

from ..utils.logger import get_logger

logger = get_logger(__name__)


def prewarm_models() -> dict[str, str]:
    """Load configured model backends and return observable per-model status.

    This function is intentionally opt-in from application lifespans. Model
    loaders own their dependency and missing-weight handling, so a failed
    prewarm must not prevent the web application from starting.
    """
    loaders: dict[str, Callable[[], str]] = {}

    def load_moldet() -> str:
        from .moldet_v2_ft import get_moldet

        detector = get_moldet()
        return (
            "ready"
            if detector is not None and detector.is_available()
            else "unavailable"
        )

    def load_molparser() -> str:
        from . import molparser

        molparser.load()
        # molparser.load() swallows failures internally, so ask health().
        status = molparser.health().get("status", "error")
        return status if status in ("ready", "error") else "unavailable"

    loaders.update(moldet=load_moldet, molparser=load_molparser)
    statuses: dict[str, str] = {}
    from ..infra.models import ensure as ensure_model_status

    for name, loader in loaders.items():
        ensure_model_status(name, "loading")
        logger.info("model_loading model=%s", name)
        try:
            # One model raising must never skip the remaining loaders.
            statuses[name] = loader()
            ensure_model_status(name, statuses[name])
            logger.info("model_loading model=%s status=%s", name, statuses[name])
        except Exception as exc:
            statuses[name] = "error"
            ensure_model_status(name, "error")
            logger.warning("model_loading model=%s status=error error=%s", name, exc)
    return statuses

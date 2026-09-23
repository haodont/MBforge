"""Runtime capability port used by HTTP and application use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeProvider:
    """Runtime capabilities supplied by the adapter composition root."""

    resource_manager: Any
    model_locator: Any
    model_status: Any
    models: Any
    molparser: Any
    moldet: Any
    hiro_layout: Any
    table_slanet: Any
    ocr_crop_labels: Any
    ocr_label_reader: Any
    ocr_page_text: Any
    llm: Any
    process: Any
    ingest_queue: Any
    ingest_worker: Any


_provider: RuntimeProvider | None = None


def configure_runtime_provider(provider: RuntimeProvider) -> None:
    """Install the concrete runtime provider during composition."""

    global _provider
    _provider = provider


def get_runtime() -> RuntimeProvider:
    """Return the configured runtime capability set."""

    if _provider is None:
        raise RuntimeError(
            "runtime provider is not configured; build the application through "
            "mbforge.app or configure it in the test composition root"
        )
    return _provider


__all__ = ["RuntimeProvider", "configure_runtime_provider", "get_runtime"]

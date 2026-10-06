"""Concrete runtime capability composition."""

# Tests:
#   tests/conftest.py
#   tests/unit/test_runtime_provider.py

from __future__ import annotations

import importlib

from mbforge.foundation import docking as docking_engine
from mbforge.foundation.inference import hiro_layout, moldet_v2_ft
from mbforge.foundation.inference.ocr import crop_labels as ocr_crop_labels
from mbforge.foundation.inference.ocr import label_reader as ocr_label_reader
from mbforge.foundation.inference.ocr import page_text as ocr_page_text
from mbforge.server import (
    models,
    process,
    resource_manager,
)
from mbforge.server.docking import worker as docking_worker
from mbforge.server.ingest import queue as ingest_queue
from mbforge.server.ingest import worker as ingest_worker
from mbforge.service.ports.runtime import RuntimeProvider


class _DynamicModule:
    """Resolve a package module lazily so test and plugin substitutions work."""

    def __init__(self, package: str, attribute: str) -> None:
        self._package = package
        self._attribute = attribute

    def __getattr__(self, name: str):
        package = importlib.import_module(self._package)
        return getattr(getattr(package, self._attribute), name)


def create_runtime_provider() -> RuntimeProvider:
    """Build the lazily-used model, OCR reader and process capabilities.

    There is no LLM capability: the chat agent runs in its own Node sidecar
    (agent/) and owns every provider call.
    """

    return RuntimeProvider(
        resource_manager=resource_manager.ResourceManager,
        model_status=models,
        models=models,
        molparser=_DynamicModule("mbforge.foundation.inference", "molparser"),
        moldet=moldet_v2_ft,
        hiro_layout=hiro_layout,
        table_slanet=_DynamicModule("mbforge.foundation.inference", "table_slanet"),
        ocr_crop_labels=ocr_crop_labels,
        ocr_label_reader=ocr_label_reader,
        ocr_page_text=ocr_page_text,
        process=process,
        ingest_queue=ingest_queue,
        ingest_worker=ingest_worker,
        docking_engine=docking_engine,
        docking_worker=docking_worker,
    )


__all__ = ["create_runtime_provider"]

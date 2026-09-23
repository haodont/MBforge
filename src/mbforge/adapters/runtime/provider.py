"""Concrete runtime capability composition."""

from __future__ import annotations

import importlib

from mbforge.adapters.inference import hiro_layout, moldet_v2_ft
from mbforge.adapters.inference.ocr import crop_labels as ocr_crop_labels
from mbforge.adapters.inference.ocr import label_reader as ocr_label_reader
from mbforge.adapters.inference.ocr import page_text as ocr_page_text
from mbforge.adapters.runtime import (
    llm,
    model_locator,
    models,
    process,
    resource_manager,
)
from mbforge.adapters.runtime.ingest import queue as ingest_queue
from mbforge.adapters.runtime.ingest import worker as ingest_worker
from mbforge.application.ports.runtime import RuntimeProvider


class _DynamicModule:
    """Resolve a package module lazily so test and plugin substitutions work."""

    def __init__(self, package: str, attribute: str) -> None:
        self._package = package
        self._attribute = attribute

    def __getattr__(self, name: str):
        package = importlib.import_module(self._package)
        return getattr(getattr(package, self._attribute), name)


def create_runtime_provider() -> RuntimeProvider:
    """Build the lazily-used model, OCR reader, LLM and process capabilities."""

    return RuntimeProvider(
        resource_manager=resource_manager.ResourceManager,
        model_locator=model_locator,
        model_status=models,
        models=models,
        molparser=_DynamicModule("mbforge.adapters.inference", "molparser"),
        moldet=moldet_v2_ft,
        hiro_layout=hiro_layout,
        table_slanet=_DynamicModule(
            "mbforge.adapters.inference", "table_slanet"
        ),
        ocr_crop_labels=ocr_crop_labels,
        ocr_label_reader=ocr_label_reader,
        ocr_page_text=ocr_page_text,
        llm=llm,
        process=process,
        ingest_queue=ingest_queue,
        ingest_worker=ingest_worker,
    )


__all__ = ["create_runtime_provider"]

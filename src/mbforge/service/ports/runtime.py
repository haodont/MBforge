"""Runtime capability port used by HTTP and application use cases.

Each field is a narrow :class:`Protocol` capturing the methods the application
actually calls, so consumers are typed against the capability boundary without
importing the concrete adapter modules. ``process``/``ingest_queue``/
``ingest_worker`` are process-level handles passed through opaquely, so they
stay ``Any``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ResourceManagerCapability(Protocol):
    catalog: Any

    def check(self, resource_id: str) -> Any: ...

    def check_all(self) -> Any: ...

    def ensure(self, resource_id: str) -> Any: ...


class ModelStatusCapability(Protocol):
    def get_all(self) -> Any: ...

    def ensure(self, model_id: str, status: str) -> None: ...


class ModelsCapability(Protocol):
    def loaded(self) -> Any: ...

    def clear(self, model_id: str) -> Any: ...

    def test(self, model_id: str, subpath: Any) -> Any: ...


class MolparserCapability(Protocol):
    def health(self) -> dict[str, Any]: ...

    def predict(self, image: Any) -> Any: ...

    def load(self) -> None: ...


class MoldetCapability(Protocol):
    def detect_molecules(self, *args: Any, **kwargs: Any) -> Any: ...

    def detect_molecules_batch(self, *args: Any, **kwargs: Any) -> Any: ...

    def to_api_dict(self, result: Any) -> Any: ...


class HiroLayoutCapability(Protocol):
    def get_hiro(self) -> Any: ...

    def detect_regions(self, image: Any, detector: Any, *, threshold: float) -> Any: ...


class TableSlanetCapability(Protocol):
    def predict_table(self, crop: Any) -> Any: ...


class OcrCropLabelsCapability(Protocol):
    def extract_label_reads(self, image: Any) -> Any: ...


class OcrPageTextCapability(Protocol):
    def read_text_in_boxes(self, image: Any, boxes: Any) -> Any: ...


class OcrLabelReaderCapability(Protocol):
    def get_label_reader(self) -> Any: ...


@dataclass(frozen=True)
class RuntimeProvider:
    """Runtime capabilities supplied by the adapter composition root."""

    resource_manager: ResourceManagerCapability
    model_status: ModelStatusCapability
    models: ModelsCapability
    molparser: MolparserCapability
    moldet: MoldetCapability
    hiro_layout: HiroLayoutCapability
    table_slanet: TableSlanetCapability
    ocr_crop_labels: OcrCropLabelsCapability
    ocr_label_reader: OcrLabelReaderCapability
    ocr_page_text: OcrPageTextCapability
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
            "mbforge.server.app or configure it in the test composition root"
        )
    return _provider


__all__ = [
    "RuntimeProvider",
    "configure_runtime_provider",
    "get_runtime",
]

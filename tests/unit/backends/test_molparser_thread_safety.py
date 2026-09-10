from __future__ import annotations

import threading
import time

import pytest
from PIL import Image

from mbforge.backends import molparser as molparser_module
from mbforge.backends.molparser import load, predict, predict_batch


@pytest.fixture
def _restore_state():
    orig_model = molparser_module._MODEL
    orig_available = molparser_module._AVAILABLE
    orig_error = molparser_module._ERROR
    molparser_module._MODEL = None
    molparser_module._AVAILABLE = False
    molparser_module._ERROR = ""
    try:
        yield
    finally:
        molparser_module._MODEL = orig_model
        molparser_module._AVAILABLE = orig_available
        molparser_module._ERROR = orig_error


class _SerializedRecognizer:
    """Tracks the maximum number of concurrent recognize() calls."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def recognize(self, images):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.02)
        with self._lock:
            self.active -= 1
        return ["C" for _ in images]


def _img() -> Image.Image:
    return Image.new("RGB", (8, 8), "white")


def _install(recognizer) -> None:
    molparser_module._MODEL = recognizer
    molparser_module._AVAILABLE = True


def test_predict_and_predict_batch_are_mutually_exclusive(_restore_state):
    fake = _SerializedRecognizer()
    _install(fake)
    threads = [
        threading.Thread(target=lambda: predict(_img())),
        threading.Thread(target=lambda: predict_batch([_img()])),
        threading.Thread(target=lambda: predict(_img())),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert fake.max_active == 1


def test_load_concurrent_first_call_creates_single_model(monkeypatch, _restore_state):
    """Concurrent first calls to molparser.load create only one model instance."""
    construct_count = {"n": 0}
    count_lock = threading.Lock()

    def _fake_init(self, model_path, *, device, max_length=256):
        with count_lock:
            construct_count["n"] += 1
        self.model_path = model_path
        self.device = device
        self.max_length = max_length

    fake_recognizer = type(
        "FakeRecognizer",
        (),
        {
            "__init__": _fake_init,
            "recognize": lambda self, images: ["C" for _ in images],
        },
    )
    monkeypatch.setattr(
        "molparser.models.runtime.MolParserRecognizer",
        fake_recognizer,
    )
    monkeypatch.setattr(
        molparser_module,
        "is_gpu_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "mbforge.infra.resource_manager.ResourceManager.get_molparser_path",
        staticmethod(lambda: "/fake/path"),
    )

    models = []
    result_lock = threading.Lock()

    def _target():
        load()
        with result_lock:
            models.append(molparser_module._MODEL)

    threads = [threading.Thread(target=_target) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(m) for m in models}) == 1
    assert construct_count["n"] == 1

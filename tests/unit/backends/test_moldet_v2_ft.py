from __future__ import annotations

import threading
from unittest.mock import MagicMock

from PIL import Image

from mbforge.foundation.inference import moldet_v2_ft as moldet_module
from mbforge.foundation.inference.moldet_v2_ft import (
    MolDetv2Detector,
    detect_molecules,
    detect_molecules_batch,
    get_moldet,
)


def test_get_moldet_concurrent_first_call_creates_single_instance(monkeypatch):
    """Concurrent first calls to get_moldet create only one detector instance."""
    # Reset singleton so this test observes first-call behavior.
    moldet_module._detector_singleton = None

    load_count = {"n": 0}
    count_lock = threading.Lock()

    def _fake_load_model(self):
        with count_lock:
            load_count["n"] += 1
        self.model = "fake-model"

    monkeypatch.setattr(moldet_module.MolDetv2Detector, "_load_model", _fake_load_model)

    detectors = []
    result_lock = threading.Lock()

    def _target():
        detector = get_moldet()
        with result_lock:
            detectors.append(detector)

    threads = [threading.Thread(target=_target) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(d) for d in detectors}) == 1
    assert load_count["n"] == 1


def test_detect_molecules_normalizes_filters_and_maps_results(monkeypatch):
    """``detect_molecules`` normalizes/filters raw boxes, and
    ``detect_molecules_batch`` forwards the whole image list once and maps one
    result per image in order — degrading to one empty result per image when
    the model is unavailable."""
    detector = object.__new__(MolDetv2Detector)
    monkeypatch.setattr(detector, "is_available", lambda: True)
    monkeypatch.setattr(
        detector,
        "detect",
        lambda image: [
            (10.0, 20.0, 50.0, 100.0, 0.9, 1),
            (0.0, 0.0, 20.0, 20.0, 0.2, 1),
            (0.0, 0.0, 20.0, 20.0, 0.9, 3),
        ],
    )

    result = detect_molecules(Image.new("RGB", (100, 200)), detector)
    assert result.bboxes == [moldet_module.MoleculeBbox(1, (0.1, 0.1, 0.5, 0.5), 0.9)]

    batch_detector = object.__new__(MolDetv2Detector)
    monkeypatch.setattr(batch_detector, "is_available", lambda: True)
    seen: list[tuple[list[Image.Image], int]] = []

    def _fake_detect_batch(images, max_per_call=0):
        seen.append((list(images), max_per_call))
        return [
            [(10.0, 20.0, 50.0, 100.0, 0.9, 1)],
            [],
            [(5.0, 5.0, 9.0, 9.0, 0.95, 1)],
        ]

    monkeypatch.setattr(batch_detector, "detect_batch", _fake_detect_batch)

    images = [
        Image.new("RGB", (100, 200)),
        Image.new("RGB", (50, 50)),
        Image.new("RGB", (10, 10)),
    ]
    results = detect_molecules_batch(images, detector=batch_detector)

    assert len(seen) == 1
    assert seen[0][0] == images
    assert results[0].bboxes == [
        moldet_module.MoleculeBbox(1, (0.1, 0.1, 0.5, 0.5), 0.9)
    ]
    assert results[1].bboxes == []
    assert results[2].bboxes == [
        moldet_module.MoleculeBbox(1, (0.5, 0.5, 0.9, 0.9), 0.95)
    ]

    # An unavailable model degrades to one empty result per image.
    unavailable = object.__new__(MolDetv2Detector)
    unavailable.model = None
    assert [
        r.bboxes
        for r in detect_molecules_batch(
            [Image.new("RGB", (8, 8)) for _ in range(2)], unavailable
        )
    ] == [[], []]


def test_detect_batch_chunks_predict_calls(monkeypatch):
    """max_per_call splits the image list into predict calls of [2, 2, 1]."""
    detector = object.__new__(MolDetv2Detector)
    monkeypatch.setattr(detector, "is_available", lambda: True)
    call_sizes: list[int] = []

    def _fake_predict(images):
        call_sizes.append(len(images))
        results = []
        for _ in images:
            result = MagicMock()
            result.boxes = None
            results.append(result)
        return results

    monkeypatch.setattr(detector, "_predict", _fake_predict)

    images = [Image.new("RGB", (10, 10)) for _ in range(5)]
    grouped = detector.detect_batch(images, max_per_call=2)

    assert call_sizes == [2, 2, 1]
    assert len(grouped) == 5
    assert all(group == [] for group in grouped)

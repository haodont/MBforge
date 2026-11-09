"""Contract tests for the agent's read-only molecule-recognition tool.

The tool endpoint renders one stored PDF page and returns what the local
detector/recognizer saw. Two things are easy to break silently and are
protected here: the PDF-point (bottom-left) box contract the overlay also
uses, and the ``region`` filter that lets the model ask about one table cell
instead of the whole page.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mbforge.service.use_cases.molecule import recognition


class _Detector:
    def __init__(self, boxes: list[tuple[float, float, float, float]]) -> None:
        self._boxes = boxes
        self.thresholds: list[float] = []

    def detect_molecules(self, _image, *, mol_conf_threshold: float):
        self.thresholds.append(mol_conf_threshold)
        boxes = [SimpleNamespace(bbox=box, score=0.9) for box in self._boxes]
        return SimpleNamespace(bboxes=boxes)


class _Recognizer:
    def __init__(self) -> None:
        self.calls = 0

    def load(self) -> None:
        pass

    def predict(self, _crop):
        self.calls += 1
        return SimpleNamespace(smiles=f"C{self.calls}", esmiles=f"E{self.calls}")


class _LabelReader:
    def read(self, _image):
        return [("22A", 1.0, (0, 0, 1, 1), True)]


def _runtime(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[SimpleNamespace, _Detector, _Recognizer]:
    detector = _Detector(boxes)
    recognizer = _Recognizer()
    runtime = SimpleNamespace(
        moldet=detector,
        molparser=recognizer,
        ocr_label_reader=SimpleNamespace(get_label_reader=lambda: _LabelReader()),
    )
    return runtime, detector, recognizer


def test_recognize_page_returns_pdf_point_boxes_and_labels(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A detected structure round-trips to bottom-left PDF points with its label."""
    runtime, detector, recognizer = _runtime([(0.1, 0.1, 0.3, 0.3)])
    monkeypatch.setattr(recognition, "get_runtime", lambda: runtime)

    result = recognition.recognize_page_molecules(str(sample_pdf), page=1)

    assert result["count"] == 1
    assert result["truncated"] is False
    assert detector.thresholds == [recognition.MIN_CONFIDENCE]
    molecule = result["molecules"][0]
    assert molecule["smiles"] == "C1"
    assert molecule["labels"] == ["22A"]
    assert recognizer.calls == 1
    # 612x792 pt page, top-left box -> bottom-left points.
    assert molecule["bbox_pdf"] == pytest.approx([61.2, 554.4, 183.6, 712.8])


def test_recognize_page_region_keeps_only_intersecting_structures(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A region selects the structures the model actually asked about."""
    runtime, _detector, _recognizer = _runtime(
        [(0.1, 0.1, 0.3, 0.3), (0.6, 0.1, 0.8, 0.3)]
    )
    monkeypatch.setattr(recognition, "get_runtime", lambda: runtime)

    result = recognition.recognize_page_molecules(
        str(sample_pdf), page=1, region=[0.0, 0.0, 306.0, 792.0]
    )

    assert result["count"] == 1
    assert result["region"] == [0.0, 0.0, 306.0, 792.0]
    assert result["molecules"][0]["bbox_pdf"][0] == pytest.approx(61.2)


def test_recognize_page_reports_truncation_instead_of_dropping_silently(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hitting the cap is visible to the model, never a silent partial list."""
    boxes = [(0.1 * i, 0.1, 0.1 * i + 0.1, 0.3) for i in range(1, 4)]
    runtime, _detector, recognizer = _runtime(boxes)
    monkeypatch.setattr(recognition, "get_runtime", lambda: runtime)

    result = recognition.recognize_page_molecules(
        str(sample_pdf), page=1, max_molecules=2
    )

    assert result["count"] == 2
    assert result["truncated"] is True
    assert recognizer.calls == 2

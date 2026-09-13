"""Unit tests for crop-label OCR (identifier extraction from "others" images)."""

from __future__ import annotations

from PIL import Image

from mbforge.backends.ocr import crop_labels
from mbforge.backends.ocr.crop_labels import (
    extract_label_reads,
    filter_label_texts,
)


def test_filter_label_texts_keeps_digit_and_roman_identifiers() -> None:
    """Compound ids survive; structure formulas, stereo/R-group markers and
    prose are dropped (surveyed against real crop OCR reads)."""
    reads = [
        ("4A", 0.95),
        ("II", 0.95),
        ("iv", 0.9),
        ("I-1", 0.9),
        ("CF3", 0.9),
        ("NH", 0.99),
        ("(S)", 0.8),
        ("R1", 0.9),
        ("TBAF", 0.9),
        ("the yield of the reaction was", 0.98),
        ("", 0.9),
        ("8b", 0.4),
        ("·", 0.99),
        ("11-a", 0.9),
        ("10", 0.9),
        ("4A", 0.9),
    ]

    assert filter_label_texts(reads) == ["4A", "II", "iv", "I-1", "11-a", "10"]


def test_extract_label_reads_keeps_positions_and_isolation(monkeypatch) -> None:
    """Reads carry tight bboxes and isolation; in-line fragments are demoted."""

    class _FakeEngine:
        def __call__(self, arr):
            return [
                # standalone compound number, own line
                ([[0, 0], [10, 0], [10, 8], [0, 8]], "21", 0.99),
                # "3c" fragment of a prose line: c sits beside the 3
                ([[490, 100], [500, 100], [500, 112], [490, 112]], "3", 0.98),
                ([[502, 100], [510, 100], [510, 112], [502, 112]], "c", 0.9),
                # group formula, dropped by the whitelist
                ([[5, 200], [15, 200], [15, 210], [5, 210]], "NH", 0.99),
            ], None

    monkeypatch.setattr(crop_labels, "_ENGINE", _FakeEngine())
    reads = extract_label_reads(Image.new("L", (20, 20), 255))
    assert reads == [
        ("21", 0.99, (0, 0, 10, 8), True),
        ("3", 0.98, (490, 100, 500, 112), False),
    ]


def test_extract_label_reads_returns_empty_on_engine_failure(
    monkeypatch,
) -> None:
    """An OCR engine crash degrades to no reads instead of failing extraction.

    The read-level contract (not the one-line ``extract_label_texts`` wrapper)
    owns the error boundary: labels are enrichment only and must never raise.
    """

    class _Boom:
        def __call__(self, arr):
            raise RuntimeError("onnx backend exploded")

    monkeypatch.setattr(crop_labels, "_ENGINE", _Boom())
    assert extract_label_reads(Image.new("L", (5, 5), 255)) == []


def test_create_engine_onnx_returns_none_when_backend_missing(monkeypatch) -> None:
    """Missing onnxruntime degrades to None (silent empty OCR), never crashes.

    Protects the "labels are enrichment only" contract when rapidocr-onnxruntime
    is not installed (torch is now the primary engine and onnx is optional).
    """
    import builtins

    real_import = builtins.__import__

    def _block_onnxruntime(name, *args, **kwargs):
        if "rapidocr_onnxruntime" in name:
            raise ImportError("rapidocr-onnxruntime not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_onnxruntime)
    # Optionally drop the already-imported module so the import is re-attempted.
    import sys

    monkeypatch.delitem(sys.modules, "rapidocr_onnxruntime", raising=False)

    assert crop_labels._create_engine("onnx") is None

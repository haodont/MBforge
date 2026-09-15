"""Unit tests for the OCR fallback chain."""

from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.backends.ocr import build_backends, extract_text_with_chain
from mbforge.backends.ocr.base import OCRResult
from mbforge.backends.ocr.chain import (
    OCRUnavailableError,
    _priority_from_config,
)


def test_build_backends_has_no_cloud_backend_without_keys() -> None:
    """Cloud-only mode must not initialize backends when keys are absent."""
    backends = build_backends({})
    assert [b.name for b in backends] == []


def test_priority_config_reorders_and_completes_default_chain() -> None:
    """Configured providers come first; omitted providers retain fallback order.

    ``paddleocr_local`` and ``glmocr`` are opt-in defaults: they are nominally
    part of the chain (so setting their host/api_key enables them without
    editing ``priority``), but ``build_backends`` drops them unless configured —
    see ``test_build_backends_has_no_cloud_backend_without_keys``.
    """
    assert _priority_from_config({"priority": ["paddleocr", "unknown"]}) == [
        "paddleocr",
        "glmocr",
        "paddleocr_local",
    ]


def test_extract_text_with_chain_reports_no_backend_as_explicit_error() -> None:
    """Cloud-only extraction must fail explicitly when no provider is configured."""
    with pytest.raises(OCRUnavailableError, match="no OCR backend"):
        extract_text_with_chain(b"fake png bytes", {})


def test_extract_text_with_chain_reuses_supplied_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller can reuse initialized cloud clients across page retries."""

    class _Backend:
        name = "fake-cloud"

        def extract_text(self, _image: bytes) -> OCRResult:
            return OCRResult(text="cloud text")

    monkeypatch.setattr(
        "mbforge.backends.ocr.chain.build_backends",
        lambda _cfg: (_ for _ in ()).throw(AssertionError("rebuilt chain")),
    )
    result = extract_text_with_chain(b"png", {}, backends=[_Backend()])
    assert result.text == "cloud text"
    assert result.backend == "fake-cloud"
    assert result.chain_attempts == 1
    assert result.elapsed_ms >= 0


def test_extract_text_with_chain_saves_images_when_backend_returns_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The chain should persist images when save_images_dir is provided."""

    class _ImageBackend:
        name = "image_backend"

        def extract_text(self, _image: bytes) -> OCRResult:
            return OCRResult(text="backend text", images={"page_1.jpg": b"img"})

    monkeypatch.setattr(
        "mbforge.backends.ocr.chain.build_backends", lambda _cfg: [_ImageBackend()]
    )

    out_dir = tmp_path / "saved"
    result = extract_text_with_chain(b"png", {}, save_images_dir=out_dir)
    assert result.text == "backend text"
    assert (out_dir / "page_1.jpg").read_bytes() == b"img"

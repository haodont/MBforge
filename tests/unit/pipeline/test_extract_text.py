"""Unit tests for the OCR-only PDF text extraction contract."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest

from mbforge.backends.ocr.base import OCRResult
from mbforge.backends.ocr.chain import OCRUnavailableError
from mbforge.pipeline.extract.text import (
    _extract_title,
    _ocr_pages,
    extract_document_text,
    extract_pdf_text,
)


def _make_pdf_with_pages(tmp_path: Path, page_texts: list[str]) -> Path:
    """Create a PDF where page i contains page_texts[i] at a fixed position."""
    pdf_path = tmp_path / "non_consecutive.pdf"
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_ocr_pages_non_consecutive_indices_no_index_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-consecutive page_indices must not trigger IndexError in _ocr_pages.

    Regression for issue C3: the result list is sized to ``len(page_indices)``,
    but the old code used the absolute page number as a list index.
    """
    page_texts = ["page zero", "page one", "page two", "page three", "page four"]
    pdf_path = _make_pdf_with_pages(tmp_path, page_texts)
    doc: Any = pymupdf.open(str(pdf_path))

    # Ask for pages 0, 2, 4 (non-consecutive absolute page numbers).
    requested_indices = [0, 2, 4]

    def fake_extract(image_bytes: bytes, _config: dict | None, **_kwargs) -> OCRResult:
        # Return text based on a simple marker derived from image content.
        # We don't actually OCR; just verify the right page index reached us.
        return OCRResult(text="ocr text")

    monkeypatch.setattr("mbforge.backends.ocr.extract_text_with_chain", fake_extract)
    monkeypatch.setattr(
        "mbforge.backends.ocr.build_backends",
        lambda _config: [SimpleNamespace(name="fake-cloud")],
    )

    try:
        results = _ocr_pages(doc, requested_indices, ocr_config={})
    finally:
        doc.close()

    assert len(results) == len(requested_indices)
    # All requested pages should have received the mocked OCR text.
    assert all(r == "ocr text" for r in results)


def test_ocr_pages_result_positions_align_with_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Result list order must match the order of ``page_indices`` exactly."""
    page_texts = ["A", "B", "C", "D", "E"]
    pdf_path = _make_pdf_with_pages(tmp_path, page_texts)
    doc: Any = pymupdf.open(str(pdf_path))

    requested_indices = [4, 1, 3]

    def fake_extract(image_bytes: bytes, _config: dict | None, **_kwargs) -> OCRResult:
        return OCRResult(text="aligned")

    monkeypatch.setattr("mbforge.backends.ocr.extract_text_with_chain", fake_extract)
    monkeypatch.setattr(
        "mbforge.backends.ocr.build_backends",
        lambda _config: [SimpleNamespace(name="fake-cloud")],
    )

    try:
        results = _ocr_pages(doc, requested_indices, ocr_config={})
    finally:
        doc.close()

    assert results == ["aligned", "aligned", "aligned"]


def test_ocr_pages_does_not_retry_empty_page_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Page-level retries stay disabled because the backend owns retries."""
    page_texts = ["A", "B", "C"]
    pdf_path = _make_pdf_with_pages(tmp_path, page_texts)
    doc: Any = pymupdf.open(str(pdf_path))

    requested_indices = [0, 1, 2]
    calls: list[int] = []

    def fake_extract(image_bytes: bytes, _config: dict | None, **_kwargs) -> OCRResult:
        calls.append(len(calls))
        if len(calls) == 2:
            return OCRResult(text="", error="empty")
        return OCRResult(text=f"page-{len(calls)}")

    monkeypatch.setattr("mbforge.backends.ocr.extract_text_with_chain", fake_extract)
    monkeypatch.setattr(
        "mbforge.backends.ocr.build_backends",
        lambda _config: [SimpleNamespace(name="fake-cloud")],
    )

    try:
        with pytest.raises(
            OCRUnavailableError, match="page 2 yielded no OCR text after 1 attempts"
        ):
            _ocr_pages(doc, requested_indices, ocr_config={})
    finally:
        doc.close()

    assert len(calls) == 3


def test_extract_pdf_text_preserves_ocr_page_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full OCR results are assembled in the original PDF page order."""
    pdf_path = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=612, height=792)
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr(
        "mbforge.pipeline.extract.text._ocr_pages",
        lambda *_args, **_kwargs: [
            "ocr first page",
            "ocr middle page",
            "ocr last page",
        ],
    )
    extracted = extract_pdf_text(str(pdf_path))

    assert (
        extracted.raw_text.index("ocr first")
        < extracted.raw_text.index("ocr middle")
        < extracted.raw_text.index("ocr last")
    )
    assert extracted.parser == "ocr"


def test_ocr_pages_uses_chain_backends_per_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each scanned page is OCR'd through the chain's configured backends."""
    pdf_path = _make_pdf_with_pages(tmp_path, ["", ""])
    doc: Any = pymupdf.open(str(pdf_path))
    chain_calls: list[list[str]] = []

    class _Paddle:
        name = "paddleocr"

    monkeypatch.setattr(
        "mbforge.backends.ocr.build_backends",
        lambda _config: [_Paddle()],
    )

    def fake_chain(_image: bytes, _config: dict | None, **kwargs: Any) -> OCRResult:
        backends = kwargs["backends"]
        chain_calls.append([backend.name for backend in backends])
        return OCRResult(text="paddle text", backend="paddleocr")

    monkeypatch.setattr("mbforge.backends.ocr.extract_text_with_chain", fake_chain)

    try:
        results = _ocr_pages(doc, [0, 1])
    finally:
        doc.close()

    assert results == ["paddle text", "paddle text"]
    assert chain_calls == [["paddleocr"], ["paddleocr"]]


def _cached_document(library_root: Path, doc_id: str, page_texts: list[str]) -> Any:
    """Build a Document whose extraction cache mirrors page_texts."""
    from mbforge.core.document import Document

    doc = Document(
        doc_id=doc_id,
        library_root=library_root,
        title="cached",
        file_name="source.pdf",
        page_count=len(page_texts),
    )
    doc._page_texts = list(page_texts)
    doc._page_spans = [
        [{"text": t, "bbox": [0.0, 0.0, 100.0, 20.0], "block_type": 0}]
        for t in page_texts
    ]
    return doc


def _fake_ocr_pages(calls: list[list[int]]) -> Any:
    """Return an _ocr_pages stand-in recording requested page indices."""

    def fake(
        _pdf,
        page_indices: list[int],
        ocr_config: dict | None = None,
        cancel_check=None,
        metrics: dict[int, Any] | None = None,
    ) -> list[str]:
        calls.append(list(page_indices))
        results: list[str] = []
        for idx in page_indices:
            text = f"ocr page {idx + 1}"
            results.append(text)
            if metrics is not None:
                metrics[idx] = OCRResult(
                    text=text,
                    backend="fake-cloud",
                    chain_attempts=1,
                    elapsed_ms=5,
                )
        return results

    return fake


def test_extract_document_text_uses_full_ocr_for_cached_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Document cache is not a pipeline evidence source under OCR-only."""
    page_texts = [
        "native first page with enough text" * 3,
        "",
        "native last page with enough text" * 3,
    ]
    pdf_path = _make_pdf_with_pages(tmp_path, page_texts)
    doc = _cached_document(tmp_path, "mixed-cached", page_texts)

    calls: list[list[int]] = []
    monkeypatch.setattr(
        "mbforge.pipeline.extract.text._ocr_pages", _fake_ocr_pages(calls)
    )

    extracted = extract_document_text(doc, str(pdf_path), ocr_config={})

    assert calls == [[0, 1, 2]]
    assert [p.text for p in extracted.pages] == [
        "ocr page 1",
        "ocr page 2",
        "ocr page 3",
    ]
    assert extracted.parser == "ocr"
    assert extracted.ocr_stats["pages_requested"] == 3
    assert extracted.ocr_stats["pages_succeeded"] == 3
    assert extracted.ocr_stats["backend_counts"] == {"fake-cloud": 3}


def test_extract_document_text_delegates_to_full_extraction_without_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The optional Document argument does not alter the full OCR path."""
    from mbforge.pipeline.extract.text import ExtractedDocument

    calls: list[tuple[Any, Any]] = []

    def fake_extract_pdf_text(pdf_path: str, **kwargs: Any) -> ExtractedDocument:
        calls.append((pdf_path, kwargs.get("ocr_config")))
        return ExtractedDocument(raw_text="full fallback", page_count=1)

    monkeypatch.setattr(
        "mbforge.pipeline.extract.text.extract_pdf_text", fake_extract_pdf_text
    )

    extracted = extract_document_text(
        None, str(tmp_path / "missing.pdf"), ocr_config={"paddleocr_api_key": "k"}
    )

    assert calls == [(str(tmp_path / "missing.pdf"), {"paddleocr_api_key": "k"})]
    assert extracted.raw_text == "full fallback"


# --- Title extraction (WIPO bibliographic first pages) ---


def test_extract_title_prefers_cjk_wipo_54_line() -> None:
    """The (54) 发明名称 line beats both the English (54) Title and any
    heuristic candidate on WIPO bibliographic pages."""
    text = (
        "(12) 按照专利合作条约所公布的国际申请\n"
        "\n"
        "(19) 世界知识产权组织\n"
        "国际局\n"
        "\n"
        "![](images/logo.jpg)\n"
        "\n"
        "(43) 国际公布日\n"
        "2026年2月19日(19.02.2026)\n"
        "\n"
        "(51) 国际专利分类号:\n"
        "C07D 401/12 (2006.01)\n"
        "\n"
        "(71) 申请人: 某制药公司\n"
        + "\n".join(f" filler line {i}" for i in range(30))
        + "\n"
        "(54) Title: COMPOUND SERVING AS MRGPRX2 ANTAGONIST\n"
        "\n"
        "(54) 发明名称: 作为MRGPRX2拮抗剂的化合物\n"
        "\n"
        "(57) Abstract: ...\n"
    )
    assert _extract_title(text) == "作为MRGPRX2拮抗剂的化合物"


def test_extract_title_wipo_54_english_only() -> None:
    """An English-only (54) Title line is used when no CJK variant exists."""
    text = (
        "(12) INTERNATIONAL APPLICATION PUBLISHED UNDER THE PATENT COOPERATION TREATY (PCT)\n"
        + "\n".join(f" filler line {i}" for i in range(40))
        + "\n(54) Title: KINASE INHIBITORS FOR TREATING CANCER\n"
    )
    assert _extract_title(text) == "KINASE INHIBITORS FOR TREATING CANCER"


def test_extract_title_skips_date_like_lines() -> None:
    """The publication date after ``(43)`` must never become the title."""
    text = "(43) 国际公布日\n2026年2月19日(19.02.2026)\n\n一种新型的化合物及其用途\n"
    assert _extract_title(text) == "一种新型的化合物及其用途"


def test_extract_title_explicit_prefix_still_wins() -> None:
    text = "Some header\nTitle: My Real Title\nmore text\n"
    assert _extract_title(text) == "My Real Title"


def test_extract_title_skips_image_reference() -> None:
    text = "![](images/abc.jpg)\n\nReal Document Title\n"
    assert _extract_title(text) == "Real Document Title"

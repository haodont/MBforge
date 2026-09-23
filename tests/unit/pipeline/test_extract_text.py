"""Unit tests for the local layout extract contract (text guard + title)."""

from __future__ import annotations

import pytest

from mbforge.application.pipeline.extract.text import (
    _extract_title,
    extract_layout_text,
)
from mbforge.application.pipeline.layout.parse import (
    LayoutPage,
    LayoutUnavailableError,
)


class _Detector:
    """Stand-in for the Hiro-Layout detector (available, never loaded)."""

    backend = "stub"
    model_path = "<stub>"

    def is_available(self) -> bool:
        return True


def _stub_layout(monkeypatch: pytest.MonkeyPatch, pages: list[LayoutPage]) -> None:
    monkeypatch.setattr(
        "mbforge.adapters.inference.hiro_layout.get_hiro", lambda: _Detector()
    )
    monkeypatch.setattr(
        "mbforge.application.pipeline.layout.parse.parse_pdf_layout",
        lambda *_args, **_kwargs: pages,
    )


def _empty_page() -> LayoutPage:
    return LayoutPage(page_num=1, width_pt=595.0, height_pt=842.0, dpi=144.0)


def test_layout_extract_refuses_a_document_with_no_text(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading nothing is a defect, not a result.

    The local producer is the only text source now, so a run that read no text
    anywhere would publish a document with no body — the same failure mode a
    missing detector guards against.
    """
    _stub_layout(monkeypatch, [_empty_page()])

    with pytest.raises(LayoutUnavailableError, match="read no text"):
        extract_layout_text(str(tmp_path / "x.pdf"), doc_id="d")


def test_layout_extract_allows_no_text_when_reading_is_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabling text reading is an explicit choice, not a defect."""
    _stub_layout(monkeypatch, [_empty_page()])

    extracted = extract_layout_text(
        str(tmp_path / "x.pdf"), doc_id="d", layout_config={"read_text": False}
    )

    assert extracted.raw_text == ""
    assert extracted.parser == "layout"


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

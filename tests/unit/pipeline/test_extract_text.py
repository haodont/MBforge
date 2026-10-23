"""Unit tests for the local layout extract contract (text guard + title)."""

from __future__ import annotations

import pytest

from mbforge.service.pipeline.extract.text import (
    _extract_title,
    extract_layout_text,
)
from mbforge.service.pipeline.layout.parse import (
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
        "mbforge.foundation.inference.hiro_layout.get_hiro", lambda: _Detector()
    )
    monkeypatch.setattr(
        "mbforge.service.pipeline.layout.parse.parse_pdf_layout",
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


# --- Title extraction (WIPO bibliographic first pages) ---

_WIPO_CJK_BIBLIOGRAPHY = (
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

_WIPO_ENGLISH_BIBLIOGRAPHY = (
    "(12) INTERNATIONAL APPLICATION PUBLISHED UNDER THE PATENT COOPERATION TREATY (PCT)\n"
    + "\n".join(f" filler line {i}" for i in range(40))
    + "\n(54) Title: KINASE INHIBITORS FOR TREATING CANCER\n"
)

# (page text, expected title) — the (54) line beats heuristics; dates and
# image references are never titles.
_TITLE_CASES = [
    (_WIPO_CJK_BIBLIOGRAPHY, "作为MRGPRX2拮抗剂的化合物"),
    (_WIPO_ENGLISH_BIBLIOGRAPHY, "KINASE INHIBITORS FOR TREATING CANCER"),
    (
        "(43) 国际公布日\n2026年2月19日(19.02.2026)\n\n一种新型的化合物及其用途\n",
        "一种新型的化合物及其用途",
    ),
    ("Some header\nTitle: My Real Title\nmore text\n", "My Real Title"),
    ("![](images/abc.jpg)\n\nReal Document Title\n", "Real Document Title"),
]


def test_extract_title_picks_the_bibliographic_title() -> None:
    """The (54) line (CJK first) beats heuristics; dates/images are skipped."""
    for text, expected in _TITLE_CASES:
        assert _extract_title(text) == expected, text

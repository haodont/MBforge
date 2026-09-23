"""Hiro-Layout table recognition contract (``read_tables`` / ``_fill_tables``).

``parse_page_image`` is the public boundary: table regions must carry
HTML/Markdown content when the SLANet-1M recognizer works, stay empty when
it does not, and never break the page (best-effort enrichment).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from mbforge.application.pipeline.layout.parse import parse_page_image

_HTML_TABLE = (
    "<html><body><table><thead><tr><td>Compound</td><td>IC50 (nM)</td>"
    "</tr></thead><tbody><tr><td>1a</td><td>12.5</td></tr></tbody></table>"
    "</body></html>"
)


def _box(label: str, bbox_px: tuple[float, float, float, float]):
    return SimpleNamespace(label=label, cls_id=0, score=0.9, bbox_px=bbox_px)


class _FakeRuntime:
    def __init__(self, html: str = "", error: Exception | None = None):
        self._html = html
        self._error = error
        self.table_slanet = SimpleNamespace(predict_table=self._predict_table)
        self.hiro_layout = SimpleNamespace(
            detect_regions=lambda image, detector=None, threshold=0.4: [
                _box("text", (0, 0, 100, 20)),
                _box("tab", (0, 30, 200, 80)),
            ]
        )
        self.moldet = SimpleNamespace(
            detect_molecules=lambda image: SimpleNamespace(bboxes=[])
        )
        self.ocr_page_text = SimpleNamespace(read_text_in_boxes=lambda image, boxes: {})

    def _predict_table(self, crop):
        if self._error is not None:
            raise self._error
        return self._html


def _parse(runtime: _FakeRuntime, monkeypatch, **kwargs) -> SimpleNamespace:
    monkeypatch.setattr("mbforge.application.ports.get_runtime", lambda: runtime)
    image = np.zeros((120, 220, 3), dtype=np.uint8)
    return parse_page_image(image, doc_id="doc", page_num=1, **kwargs)


def _table_region(page) -> dict:
    return next(r for r in page.regions if r["type"] == "table")


def test_parse_page_image_reads_table_regions_when_enabled(
    monkeypatch,
) -> None:
    """With ``read_tables`` the table region carries HTML and Markdown text."""
    runtime = _FakeRuntime(html=_HTML_TABLE)
    page = _parse(runtime, monkeypatch, read_tables=True)

    region = _table_region(page)
    assert region["html"] == _HTML_TABLE
    assert region["text"] == "| Compound | IC50 (nM) |\n| --- | --- |\n| 1a | 12.5 |"
    assert page.stats["table_regions"] == 1
    assert page.stats["tables_filled"] == 1


def test_parse_page_image_skips_tables_by_default(monkeypatch) -> None:
    """Table recognition is opt-in; default runs leave table regions empty."""
    page = _parse(_FakeRuntime(html=_HTML_TABLE), monkeypatch)

    assert page.stats["table_regions"] == 0
    region = _table_region(page)
    assert "html" not in region
    assert not region.get("text")


def test_parse_page_image_survives_table_recognizer_failure(monkeypatch) -> None:
    """A failing recognizer leaves the region empty and does not break the page."""
    runtime = _FakeRuntime(error=RuntimeError("boom"))
    page = _parse(runtime, monkeypatch, read_tables=True)

    region = _table_region(page)
    assert "html" not in region
    assert not region.get("text")
    assert page.stats["tables_filled"] == 0


def test_parse_page_image_keeps_table_empty_on_empty_html(monkeypatch) -> None:
    """Empty recognizer output is treated as 'no table content'."""
    page = _parse(_FakeRuntime(html=""), monkeypatch, read_tables=True)

    region = _table_region(page)
    assert "html" not in region
    assert not region.get("text")
    assert page.stats["tables_filled"] == 0

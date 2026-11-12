"""Hiro-Layout table recognition contract (``_fill_tables``).

``parse_page_image`` is the public boundary: table regions must carry
HTML/Markdown content when the SLANet-1M recognizer works, retain unsupported
HTML for review, stay empty on inference failure, and never break the page.
Recognition and structure masking are
unconditional — there is no switch that turns either off.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from mbforge.service.pipeline.layout.parse import parse_page_image

_HTML_TABLE = (
    "<html><body><table><thead><tr><td>Compound</td><td>IC50 (nM)</td>"
    "</tr></thead><tbody><tr><td>1a</td><td>12.5</td></tr></tbody></table>"
    "</body></html>"
)


def _box(label: str, bbox_px: tuple[float, float, float, float]):
    return SimpleNamespace(label=label, cls_id=0, score=0.9, bbox_px=bbox_px)


class _FakeRuntime:
    def __init__(
        self,
        html: str = "",
        error: Exception | None = None,
        molecules: tuple[tuple[float, float, float, float], ...] = (),
    ):
        self._html = html
        self._error = error
        self.predict_calls: list[dict] = []
        self.table_slanet = SimpleNamespace(predict_table=self._predict_table)
        self.hiro_layout = SimpleNamespace(
            detect_regions=lambda image, detector=None, threshold=0.4: [
                _box("text", (0, 0, 100, 20)),
                _box("tab", (0, 30, 200, 80)),
            ]
        )
        self.moldet = SimpleNamespace(
            detect_molecules=lambda image: SimpleNamespace(
                bboxes=[SimpleNamespace(bbox=box, score=0.9) for box in molecules]
            )
        )
        self.ocr_page_text = SimpleNamespace(read_text_in_boxes=lambda image, boxes: {})

    def _predict_table(self, crop, *, molecule_cells=()):
        self.predict_calls.append({"molecule_cells": list(molecule_cells)})
        if self._error is not None:
            raise self._error
        return self._html


def _parse(runtime: _FakeRuntime, monkeypatch, **kwargs) -> SimpleNamespace:
    monkeypatch.setattr("mbforge.service.ports.get_runtime", lambda: runtime)
    image = np.zeros((120, 220, 3), dtype=np.uint8)
    return parse_page_image(image, doc_id="doc", page_num=1, **kwargs)


def _table_region(page) -> dict:
    return next(r for r in page.regions if r["type"] == "table")


def test_parse_page_image_reads_table_regions(monkeypatch) -> None:
    """A table region carries the recognized HTML and Markdown text."""
    runtime = _FakeRuntime(html=_HTML_TABLE)
    page = _parse(runtime, monkeypatch)

    region = _table_region(page)
    assert region["html"] == _HTML_TABLE
    assert region["text"] == "| Compound | IC50 (nM) |\n| --- | --- |\n| 1a | 12.5 |"
    assert page.stats["table_regions"] == 1
    assert page.stats["tables_filled"] == 1


def test_parse_page_image_keeps_table_empty_without_usable_html(monkeypatch) -> None:
    """A failing recognizer or empty output leaves the region empty, page intact."""
    runtimes = [_FakeRuntime(error=RuntimeError("boom")), _FakeRuntime(html="")]

    for runtime in runtimes:
        page = _parse(runtime, monkeypatch)

        region = _table_region(page)
        assert "html" not in region
        assert not region.get("text")
        assert page.stats["tables_filled"] == 0


def test_table_drawings_are_masked_before_cell_recognition(monkeypatch) -> None:
    """A structure drawn inside a table cell never reaches cell OCR.

    The molecule box is handed to the recognizer in crop coordinates (the table
    is recognized as text, with a token at the structure's cell), and the
    token → molecule mapping is retained on the region for the evidence layer.
    Masking is not optional: any table that draws a structure is read this way.
    A table holding no drawing keeps its plain reading.
    """
    # normalized bbox → page px (77, 48, 121, 66), inside the table (0, 30, 200, 80)
    runtime = _FakeRuntime(html=_HTML_TABLE, molecules=((0.35, 0.4, 0.55, 0.55),))
    page = _parse(runtime, monkeypatch)

    cells = runtime.predict_calls[-1]["molecule_cells"]
    assert [cell["token"] for cell in cells] == ["[MOL:0]"]
    assert cells[0]["bbox"] == [77.0, 18.0, 121.0, 36.0]  # crop coords (x-0, y-30)
    region = _table_region(page)
    kept = region["molecule_cells"]
    assert len(kept) == 1
    assert kept[0]["token"] == "[MOL:0]"
    assert kept[0]["region_id"]
    assert kept[0]["bbox_pdf"]
    assert page.stats["tables_molecule_masked"] == 1
    assert page.stats["table_molecules_masked"] == 1

    plain = _FakeRuntime(html=_HTML_TABLE)
    page = _parse(plain, monkeypatch)
    assert plain.predict_calls[-1]["molecule_cells"] == []
    assert "molecule_cells" not in _table_region(page)


def test_parse_page_image_retains_conflicting_spans_for_review(monkeypatch) -> None:
    """A rejected grid must keep its raw evidence without fabricating columns."""
    html = (
        '<table><tr><td>B</td><td rowspan="2">A</td></tr>'
        '<tr><td colspan="2">C</td><td>D</td></tr></table>'
    )
    page = _parse(_FakeRuntime(html=html), monkeypatch)

    region = _table_region(page)
    assert region["html"] == html
    assert region["text"] == html
    assert page.stats["tables_filled"] == 0
    assert page.stats["tables_unconverted"] == 1

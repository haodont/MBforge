"""Extract-branch text and layout from the local layout producer.

Page text, layout spans and coordinate frames all come from the local
Hiro-Layout producer (:mod:`mbforge.application.pipeline.layout.parse`): one
144 DPI render per page is detected, merged, ordered and read with the local
RapidOCR reader. There is no cloud OCR provider and no native PyMuPDF text
source — page content is uniform so the evidence model downstream
(``source_evidence``) has a single coordinate and ``block_type`` convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mbforge.application.pipeline.cancellation import CancelCheck
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.extract.text")

#: RegionType → the pipeline's ``block_type`` convention (0=text, 1=image/figure,
#: 2=table). Only used to derive the legacy ``text_spans`` / ``figure_bboxes``
#: views from layout regions; the typed region list keeps the exact label.
_REGION_TYPE_BLOCK_TYPE: dict[str, int] = {
    "text": 0,
    "title": 0,
    "formula": 0,
    "header": 0,
    "footer": 0,
    "page_number": 0,
    "table": 2,
    "image": 1,
    "chart": 1,
    "reaction": 1,
    "seal": 1,
    "noise": 1,
    "molecule": 1,
}


def _block_type_for(region_type: str) -> int:
    """Map a layout RegionType onto the pipeline ``block_type`` convention."""
    return _REGION_TYPE_BLOCK_TYPE.get(region_type, 0)


@dataclass
class TextSpan:
    """One text, table, or image block from a PDF page with its bounding box."""

    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF pts
    block_type: int = 0  # 0=text, 1=image, 2=table


@dataclass
class PageContent:
    page_num: int  # 1-based
    text: str
    ocr_dpi: int = 0
    text_spans: list[TextSpan] = field(default_factory=list)
    figure_bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    """Figure/image region bboxes from the layout producer (bottom-left points)."""
    regions: list[dict[str, Any]] = field(default_factory=list)
    """Typed layout regions as the detector emitted them.

    Each entry carries the producer's own ``kind`` label, ``bbox`` (PDF points,
    bottom-left) and any recognized ``text``.
    """
    ocr_backend: str | None = None
    ocr_attempts: int = 0
    ocr_elapsed_ms: int = 0
    ocr_error: str | None = None


@dataclass
class ExtractedDocument:
    raw_text: str
    page_count: int
    parser: str = "layout"
    title: str | None = None
    pages: list[PageContent] = field(default_factory=list)
    ocr_stats: dict[str, Any] = field(default_factory=dict)
    kind_vocab: dict[str, str] = field(default_factory=dict)
    """``{label: category}`` for the region kinds this producer emitted.

    Declared so the join stage can register the labels it will see
    (``register_kind_vocab``) without knowing the detector.
    """


def extract_layout_text(
    pdf_path: str,
    *,
    doc_id: str,
    layout_config: dict | None = None,
    cancel_check: CancelCheck | None = None,
) -> ExtractedDocument:
    """Extract page layout and text with the local Hiro-Layout pipeline.

    This is the only Extract source: page text comes from the **layout-guided**
    local recognition over the detector's own ``text`` regions, and every page
    also carries the typed **region list** (detector ``kind`` labels), which the
    evidence join turns into ``SourceEvidence`` rows.

    With ``cross_model`` the layout producer also runs MolDet on the same render,
    so a figure region that is really one molecule is re-typed as one and a
    figure holding several molecules stays a container.

    ``text_spans`` / ``figure_bboxes`` are derived from the same regions so the
    markdown stage keeps its layout anchors; the join treats the regions as the
    authoritative layout for such a page and does not mint them twice.

    Raises:
        LayoutUnavailableError: when the detector is unavailable, or when text
            reading was requested and no page yielded any text — a run must not
            silently degrade into an evidenceless document.
    """
    from mbforge.application.pipeline.layout.labels import kind_vocab
    from mbforge.application.pipeline.layout.parse import (
        DEFAULT_CONF,
        LayoutUnavailableError,
        parse_pdf_layout,
    )
    from mbforge.application.ports import get_runtime

    detector = get_runtime().hiro_layout.get_hiro()
    if not detector.is_available():
        raise LayoutUnavailableError(
            "Hiro-Layout model is not available; cannot produce a local layout "
            f"(weights: {detector.model_path})"
        )

    config = layout_config or {}
    read_text = bool(config.get("read_text", True))
    layout_pages = parse_pdf_layout(
        pdf_path,
        doc_id=doc_id,
        conf=float(config.get("conf_threshold", DEFAULT_CONF)),
        read_text=read_text,
        read_tables=bool(config.get("read_tables", False)),
        cross_model=bool(config.get("cross_model", True)),
        max_pages=config.get("max_pages_per_doc"),
        cancel_check=cancel_check,
        detector=detector,
    )

    pages: list[PageContent] = []
    region_counts: list[int] = []
    for layout_page in layout_pages:
        regions = [_artifact_region(region) for region in layout_page.regions]
        text_spans = [
            TextSpan(
                text=str(region.get("text") or ""),
                bbox=tuple(float(v) for v in region["bbox"]),
                block_type=_block_type_for(str(region["type"])),
            )
            for region in regions
            if _block_type_for(str(region["type"])) in (0, 2)
        ]
        figure_bboxes = [
            tuple(float(v) for v in region["bbox"])
            for region in regions
            if _block_type_for(str(region["type"])) == 1
        ]
        page_text = "\n".join(
            str(region.get("text") or "").strip()
            for region in regions
            if str(region.get("text") or "").strip()
        )
        pages.append(
            PageContent(
                page_num=layout_page.page_num,
                text=page_text,
                ocr_dpi=int(round(layout_page.dpi)),
                text_spans=text_spans,
                figure_bboxes=figure_bboxes,
                regions=regions,
                ocr_backend=f"layout:{detector.backend}",
            )
        )
        region_counts.append(len(regions))

    full_text = "\n\n".join(page.text for page in pages if page.text.strip())
    if read_text and not full_text.strip():
        # Same rationale as a missing detector: an evidenceless document is a
        # defect, not a result. Only enforced when reading was requested.
        raise LayoutUnavailableError(
            f"the local layout producer read no text from any of the {len(pages)} "
            "page(s); refusing to publish an evidenceless document"
        )

    return ExtractedDocument(
        raw_text=full_text,
        page_count=len(pages),
        parser="layout",
        title=_extract_title(pages[0].text if pages else ""),
        pages=pages,
        ocr_stats={
            "pages_requested": len(pages),
            "pages_succeeded": sum(1 for page in pages if page.text.strip()),
            "pages_failed": sum(1 for page in pages if not page.text.strip()),
            "backend_counts": {detector.backend: len(pages)},
            "regions": region_counts,
            "elapsed_ms": 0,
        },
        kind_vocab=kind_vocab(),
    )


def _artifact_region(region: dict[str, Any]) -> dict[str, Any]:
    """Project a layout region onto the branch artifact's region shape."""
    return {
        "region_id": str(region.get("region_id", "")),
        "kind": str(region.get("label", "")),
        "type": str(region.get("type", "")),
        "bbox": [round(float(v), 2) for v in region.get("bbox_pdf", [])],
        "score": round(float(region.get("score", 0.0)), 4),
        "reading_order": int(region.get("reading_order", 0)),
        "source": str(region.get("source", "")),
        "text": str(region.get("text") or ""),
    }


def _extract_title(text: str) -> str | None:
    """Extract a title from the first page text.

    Strategy:
    1. If a line starts with ``Title:`` / ``标题：`` / ``题目：``, take the rest.
    2. WIPO bibliographic pages carry the real title on the ``(54)`` line
       (``(54) Title: ...`` / ``(54) 发明名称: ...``) — prefer it over any
       heuristic candidate, and prefer the CJK variant when both an English
       and a native-language ``(54)`` line exist.
    3. Otherwise pick the first substantive non-empty line, skipping:
       - PCT/WIPO bibliographic headers (``(NN) ...``)
       - Classification codes (``(51) ...``)
       - Image references and date-like lines (publication date, etc.)
       - Long ALL-CAPS lines
    4. Cap at 200 chars.
    """
    if not text:
        return None

    # 1. explicit prefix wins
    for line in text.split("\n")[:30]:
        for prefix in ["Title:", "标题：", "题目："]:
            if line.strip().startswith(prefix):
                rest = line.strip()[len(prefix) :].strip()
                if rest and 3 < len(rest) < 200:
                    return rest

    # 2. WIPO (54) title line — the authoritative title on bibliographic
    # pages, which the generic ``(NN)`` skip below would otherwise discard.
    # Scan deep: the (54) block sits after applicants/inventors (~line 50).
    _wipo_title = re.compile(r"^\(54\)\s*(?:Title|发明名称|题目)?\s*[:：]?\s*(.+)$")
    _cjk = re.compile(r"[一-鿿]")
    wipo_titles = [
        m.group(1).strip()
        for line in text.split("\n")[:100]
        if (m := _wipo_title.match(line.strip())) and 3 < len(m.group(1).strip()) < 200
    ]
    if wipo_titles:
        return next((t for t in wipo_titles if _cjk.search(t)), wipo_titles[0])

    # 3. heuristic: skip bibliographic lines
    _biblio = re.compile(r"^\(\d{1,3}\)\s+")
    _all_caps = re.compile(r"^[A-Z][A-Z\s&\-,/]{4,}$")
    # Skip known patent header phrases
    _header_phrases = {
        "INTERNATIONAL APPLICATION PUBLISHED UNDER THE PATENT COOPERATION TREATY (PCT)",
        "INTERNATIONAL APPLICATION PUBLISHED UNDER THE PATENT COOPERATION TREATY",
    }
    # Publication/application dates must never become the document title
    # (they are the first non-bibliographic line after ``(43)``/``(22)``).
    _date_like = re.compile(
        r"^(?:\d{4}\s*年\s*\d{1,2}\s*月|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|"
        r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|[A-Z][a-z]+\s+\d{1,2},\s*\d{4})"
    )
    candidate_with_caps = None  # remember the first ALL-CAPS line as fallback
    _image_link = re.compile(r"^!\[.*\]\(.*\)\s*$")
    for line in text.split("\n")[:30]:
        s = line.strip()
        if not s:
            continue
        if not (3 < len(s) < 200):
            continue
        if s.isdigit():
            continue
        if _image_link.match(s):
            # OCR markdown may open with a logo/figure image reference.
            continue
        if _date_like.match(s):
            continue
        if _biblio.match(s):
            continue
        if s in _header_phrases:
            continue
        if _all_caps.match(s):
            # Patent titles are often ALL-CAPS — remember as fallback but keep
            # scanning for a more specific line.
            if candidate_with_caps is None:
                candidate_with_caps = s
            continue
        # Looks like a real title — return it
        return s
    return candidate_with_caps

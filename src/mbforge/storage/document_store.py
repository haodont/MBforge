"""Document record persistence and PDF text extraction.

``storage/{doc_id}/document.json`` is the sole source of truth for the
document record; this module is the only writer/reader of that file. PDF
text extraction fills the :class:`~mbforge.core.entities.document.Document`
extraction caches.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.entities.document import Document
from .layout import LibraryLayout


def extract_pdf_text(doc: Document) -> str:
    """Extract text from the document's PDF source file using PyMuPDF.

    Returns the concatenated text from all pages.  Also populates
    ``page_count`` and per-page text/span caches on ``doc`` as a side
    effect (single fitz open).  Returns an empty string for non-PDF
    files or on any read error.
    """
    if doc._text is not None:
        return doc._text
    if Path(doc.file_name).suffix.lower() != ".pdf":
        doc._text = ""
        return doc._text
    source = LibraryLayout(doc.library_root).storage_dir(doc.doc_id) / doc.file_name
    if not source.is_file():
        doc._text = ""
        return doc._text
    try:
        import fitz

        with fitz.open(str(source)) as pdf:
            doc._page_count = pdf.page_count
            page_texts: list[str] = []
            page_spans: list[list[dict]] = []
            for page in pdf:
                page_texts.append(page.get_text("text").strip())
                spans: list[dict] = []
                for blk in page.get_text("dict")["blocks"]:
                    b = blk["bbox"]
                    if blk["type"] == 0:  # text block
                        text_content = "\n".join(
                            "".join(
                                s.get("text", "") for s in line.get("spans", [])
                            ).rstrip("\r\n")
                            for line in blk.get("lines", [])
                        ).strip()
                        spans.append({"text": text_content, "bbox": b, "block_type": 0})
                    elif blk["type"] == 1:  # image block
                        spans.append({"text": "", "bbox": b, "block_type": 1})
                page_spans.append(spans)
            doc._page_texts = page_texts
            doc._page_spans = page_spans
            doc._text = "\n".join(page_texts).strip()
    except Exception:
        doc._text = ""
    return doc._text


def save_document(doc: Document) -> None:
    """Write the document's record to ``storage/{doc_id}/document.json``."""
    path = LibraryLayout(doc.library_root).storage_dir(doc.doc_id) / "document.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.to_json(), encoding="utf-8")


def load_document(doc_id: str, library_root: str | Path) -> Document | None:
    """Load a Document from ``storage/{doc_id}/document.json``.

    Returns ``None`` if the file does not exist.
    """
    root = Path(library_root).expanduser().resolve()
    path = LibraryLayout(root).storage_dir(doc_id) / "document.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Document.from_dict(data, root)

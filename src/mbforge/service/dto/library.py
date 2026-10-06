"""Pydantic models for the unified library.

Schemas for importing documents and reporting library configuration status.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LibraryStatus(BaseModel):
    """Library configuration status."""

    configured: bool
    root: str
    doc_count: int


# ---- Request models ----


class LibraryListDocumentsRequest(BaseModel):
    library_root: str | None = None


class LibraryDeleteDocumentsRequest(BaseModel):
    """Batch document deletion: one request removes every ``doc_ids`` entry."""

    library_root: str | None = None
    doc_ids: list[str] = Field(default_factory=list, min_length=1)


class LibraryMoleculeEvidenceUpdateRequest(BaseModel):
    library_root: str | None = None
    name: str = ""
    smiles: str = ""


class LibraryConfigureRequest(BaseModel):
    root: str = ""


# ---- Response models ----


class LibraryImportResponse(BaseModel):
    success: bool = True
    document: dict[str, Any]
    run_id: str | None = None


class LibraryDocumentsResponse(BaseModel):
    documents: list[dict[str, Any]] = []


class LibraryEvidenceItem(BaseModel):
    """One SQL-backed source-evidence row returned to the document viewer."""

    evidence_id: str
    doc_id: str
    page: int
    bbox: tuple[float, float, float, float]
    raw_text: str = ""
    kind: str
    #: Category of ``kind`` (``text`` / ``table`` / ``image`` / ``molecule``), so
    #: readers never have to match a producer label by name.
    category: str = ""
    #: Paragraph this row belongs to (``""`` when the row is not in one), the
    #: patent's own paragraph number (``"0001"``, ``None`` when unnumbered), and
    #: whether this row contributed the paragraph's first fragment. A paragraph
    #: split across a page break shares one ``paragraph_id``; its later rows
    #: carry ``paragraph_start=False``.
    paragraph_id: str = ""
    paragraph_number: str | None = None
    paragraph_start: bool = False
    #: Line index inside the paragraph, and that line's left-edge depth as the
    #: layout encoded it (``0`` = body margin, ``1``+ = an indented sub-item).
    paragraph_line: int = 0
    indent_level: int = 0


class LibraryConfigureResponse(BaseModel):
    success: bool = True
    root: str


class LibraryDeleteDocumentsResponse(BaseModel):
    success: bool = True
    deleted: int = 0


class LibraryMoleculeEvidenceUpdateResponse(BaseModel):
    success: bool = True
    evidence_id: str

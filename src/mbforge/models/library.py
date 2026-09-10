"""Pydantic models for the unified library.

Schemas for importing documents and reporting library configuration status.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LibraryStatus(BaseModel):
    """Library configuration status."""

    configured: bool
    root: str
    doc_count: int


# ---- Request models ----


class LibraryListDocumentsRequest(BaseModel):
    library_root: str | None = None


class LibraryDeleteDocumentRequest(BaseModel):
    library_root: str | None = None
    doc_id: str = ""


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
    task_id: str | None = None


class LibraryDocumentsResponse(BaseModel):
    documents: list[dict[str, Any]] = []


class LibraryEvidenceItem(BaseModel):
    """One SQL-backed source-evidence row returned to the document viewer."""

    evidence_id: str
    doc_id: str
    page: int
    bbox: tuple[float, float, float, float]
    raw_text: str = ""
    coref: str = ""
    kind: str


class LibraryConfigureResponse(BaseModel):
    success: bool = True
    root: str


class LibrarySuccessResponse(BaseModel):
    success: bool = True


class LibraryMoleculeEvidenceUpdateResponse(BaseModel):
    success: bool = True
    evidence_id: str

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


# ---- Collections (library "Groups") ----


class LibraryListCollectionsRequest(BaseModel):
    library_root: str | None = None


class LibraryCreateCollectionRequest(BaseModel):
    library_root: str | None = None
    name: str = ""
    parent_id: str | None = None


class LibraryRenameCollectionRequest(BaseModel):
    library_root: str | None = None
    collection_id: str = ""
    name: str = ""


class LibraryDeleteCollectionRequest(BaseModel):
    library_root: str | None = None
    collection_id: str = ""


class LibraryCollectionDocumentRequest(BaseModel):
    library_root: str | None = None
    collection_id: str = ""
    doc_id: str = ""


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


class LibraryConfigureResponse(BaseModel):
    success: bool = True
    root: str


class LibrarySuccessResponse(BaseModel):
    success: bool = True


class LibraryMoleculeEvidenceUpdateResponse(BaseModel):
    success: bool = True
    evidence_id: str


class CollectionInfo(BaseModel):
    """Flat per-collection summary returned to the group tree."""

    collection_id: str
    name: str
    parent_id: str | None
    doc_count: int


class CollectionNode(CollectionInfo):
    """A collection node with its nested children (recursive tree)."""

    children: list[CollectionNode] = []


class LibraryCollectionsResponse(BaseModel):
    collections: list[CollectionNode] = []


class LibraryCreateCollectionResponse(BaseModel):
    success: bool = True
    collection: dict[str, Any] | None = None
    error: str | None = None

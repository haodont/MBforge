"""Per-document entity: one library document as a simple record.

Every imported PDF is modeled as a :class:`Document`. The class holds the
document identity (``doc_id`` + ``library_root``) and the record fields
(title, file_name, page_count, status, created_at) as plain attributes.

The record serializes to and from plain dicts (the ``documents`` table row
shape). Persistence lives in :mod:`mbforge.db.document_records` and the PDF
page-count probe in :mod:`mbforge.db.pdf_probe`; artifact path resolution
belongs to :class:`~mbforge.foundation.layout.LibraryLayout`.
"""

from __future__ import annotations

from pathlib import Path


class Document:
    """A single library document -- plain record fields plus JSON codec."""

    def __init__(
        self,
        doc_id: str,
        library_root: str | Path,
        *,
        title: str = "",
        file_name: str = "",
        page_count: int = 0,
        status: str = "pending",
        created_at: str = "",
    ) -> None:
        self._doc_id = doc_id
        self._root = Path(library_root).expanduser().resolve()
        self._title = title
        self._file_name = file_name
        self._page_count = page_count
        self._status = status
        self._created_at = created_at

    # ── Identity ────────────────────────────────────────────────

    @property
    def doc_id(self) -> str:
        """Return this document's identifier."""
        return self._doc_id

    @property
    def library_root(self) -> Path:
        """Return the resolved library root this document belongs to."""
        return self._root

    # ── Record properties ───────────────────────────────────────

    @property
    def title(self) -> str:
        """Return the document title."""
        return self._title

    @property
    def file_name(self) -> str:
        """Return the sanitized original filename."""
        return self._file_name

    @property
    def page_count(self) -> int:
        """Return the page count (read from the PDF at import time)."""
        return self._page_count

    @property
    def status(self) -> str:
        """Return the document status (pending | ready | error)."""
        return self._status

    @property
    def created_at(self) -> str:
        """Return the creation timestamp."""
        return self._created_at

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return the record as a plain dict (suitable for JSON serialization)."""
        data = {
            "doc_id": self._doc_id,
            "title": self._title,
            "file_name": self._file_name,
            "page_count": self._page_count,
            "status": self._status,
            "created_at": self._created_at,
        }
        return data

    @classmethod
    def from_dict(cls, data: dict, library_root: str | Path) -> Document:
        """Construct a Document from a dict (e.g. loaded from JSON)."""
        doc = cls(
            doc_id=data["doc_id"],
            library_root=library_root,
            title=data.get("title", ""),
            file_name=data.get("file_name", ""),
            page_count=data.get("page_count", 0),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", ""),
        )
        return doc

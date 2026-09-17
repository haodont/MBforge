"""LibraryStore — unified data store for the document library.

Document records live in ``storage/{doc_id}/document.json`` (JSON-only).
The SQLite database still holds molecules, evidence, and the ingest queue,
but no longer tracks documents.
"""

from __future__ import annotations

import functools
import shutil
from pathlib import Path

from ...core.document import Document
from ...storage.document_store import extract_pdf_text, load_document, save_document
from ...storage.layout import LibraryLayout, sanitize_upload_filename
from ...utils.errors import MBForgeError, NotFoundError
from ...utils.files import ensure_dir, sha256_bytes, sha256_file
from ...utils.logger import get_logger
from .backup import create_backup

logger = get_logger("mbforge.services.documents.library")


class LibraryStore:
    """Single-library data store — documents, collections, and molecules."""

    def __init__(self, library_root: str | Path) -> None:
        self._root = Path(library_root).resolve()
        self._layout = LibraryLayout(self._root)

    @classmethod
    @functools.lru_cache(maxsize=128)
    def get(cls, library_root: str | Path) -> LibraryStore:
        """Return a cached LibraryStore instance keyed by resolved absolute path."""
        return cls(library_root)

    # ── Documents ────────────────────────────────────────────────

    def add_document(self, file_path: str | Path, title: str = "") -> Document:
        """Copy an existing on-disk file into library storage and register it.

        Raises NotFoundError if file_path is missing,
        MBForgeError if file copy fails.
        """
        src = Path(file_path).resolve()
        if not src.is_file():
            raise NotFoundError("File not found", detail=str(src))
        return self._register(src, title)

    def add_uploaded_file(
        self, content: bytes, filename: str, title: str = ""
    ) -> Document:
        """Persist a browser-uploaded file payload and register it as a document.

        Rejects empty content; raises MBForgeError if disk write fails.
        """
        if not content:
            raise MBForgeError("Empty file", detail=filename)
        if not filename:
            raise MBForgeError("Missing filename")

        safe_filename = sanitize_upload_filename(filename)
        # Content-addressed doc_id: identical bytes always map to one document.
        doc_id = sha256_bytes(content)[:32]
        existing = load_document(doc_id, self._root)
        if existing is not None:
            logger.info(
                "Duplicate content; returning existing document %s (id=%s)",
                existing.file_name,
                doc_id,
            )
            return existing
        safe_title = title.strip() if title else Path(safe_filename).stem
        storage_subdir = self._layout.storage_dir(doc_id)
        dest = storage_subdir / safe_filename

        try:
            ensure_dir(storage_subdir)
            dest.write_bytes(content)
        except (OSError, PermissionError) as e:
            if dest.exists():
                dest.unlink(missing_ok=True)
            if storage_subdir.exists() and not any(storage_subdir.iterdir()):
                storage_subdir.rmdir()
            raise MBForgeError("Failed to store file", detail=str(e)) from e

        logger.info("Uploaded document registered: %s (id=%s)", safe_title, doc_id)
        doc = Document(
            doc_id=doc_id,
            library_root=self._root,
            title=safe_title,
            file_name=safe_filename,
            status="pending",
        )
        # Extract and cache text + spans at import time so the pipeline can
        # reuse them without re-parsing the PDF.  The extraction result is
        # persisted to storage/{doc_id}/document.json via save_document().
        extract_pdf_text(doc)
        save_document(doc)
        return doc

    def add_uploaded_file_from_path(
        self, src_path: str | Path, filename: str, title: str = ""
    ) -> Document:
        """Read an on-disk file and register it as a document.

        The caller owns ``src_path`` and is responsible for removing it once
        this call returns.
        """
        src = Path(src_path)
        if not src.is_file():
            raise NotFoundError("Source file not found", detail=str(src))
        return self.add_uploaded_file(src.read_bytes(), filename, title)

    def _register(self, src: Path, title: str) -> Document:
        """Copy ``src`` into storage and save the JSON record.

        If the copy fails the JSON is never written so the library stays clean.
        """
        # Content-addressed doc_id: identical bytes always map to one document.
        doc_id = sha256_file(src)[:32]
        existing = load_document(doc_id, self._root)
        if existing is not None:
            logger.info(
                "Duplicate content; returning existing document %s (id=%s)",
                existing.file_name,
                doc_id,
            )
            return existing
        safe_title = title.strip() if title else src.stem
        storage_subdir = self._layout.storage_dir(doc_id)
        dest = storage_subdir / src.name

        try:
            ensure_dir(storage_subdir)
            shutil.copy2(str(src), str(dest))
        except (OSError, PermissionError) as e:
            if storage_subdir.exists() and not any(storage_subdir.iterdir()):
                storage_subdir.rmdir()
            raise MBForgeError("Failed to store file", detail=str(e)) from e

        logger.info("Document added: %s (id=%s)", safe_title, doc_id)
        doc = Document(
            doc_id=doc_id,
            library_root=self._root,
            title=safe_title,
            file_name=src.name,
            status="pending",
        )
        # Extract and cache text + spans at import time so the pipeline can
        # reuse them without re-parsing the PDF.  The extraction result is
        # persisted to storage/{doc_id}/document.json via save_document().
        extract_pdf_text(doc)
        save_document(doc)
        return doc

    def load_document(self, doc_id: str) -> Document | None:
        """Load a Document from ``document.json``.  ``None`` if absent."""
        return load_document(doc_id, self._root)

    def get_document(self, doc_id: str) -> Document | None:
        """Return the :class:`Document` entity for ``doc_id`` (``None`` if absent)."""
        return self.load_document(doc_id)

    def delete_document(self, doc_id: str) -> None:
        """Remove storage dir + JSON record + molecule data."""
        backup_path = create_backup(self._root, doc_id, "document_delete")
        storage_subdir = self._layout.storage_dir(doc_id)
        if storage_subdir.exists():
            shutil.rmtree(storage_subdir, ignore_errors=True)

        from ...storage.sqlite.database import DatabaseManager

        db = DatabaseManager.get(str(self._root))
        with db.transaction() as (_kb_conn, mol_conn):
            DatabaseManager.delete_document_molecule_data(mol_conn, doc_id)
        logger.info("Document deleted: %s (backup=%s)", doc_id, backup_path)

    def list_documents(self) -> list[Document]:
        """Scan ``storage/*/document.json`` and return all documents."""
        storage_root = self._layout.storage_root
        if not storage_root.is_dir():
            return []
        docs: list[Document] = []
        for entry in storage_root.iterdir():
            if not entry.is_dir():
                continue
            doc = load_document(entry.name, self._root)
            if doc is not None:
                docs.append(doc)
        docs.sort(key=lambda d: d.created_at or "", reverse=True)
        return docs

    def search_documents(self, query: str) -> list[Document]:
        """Case-insensitive substring search over title and file_name."""
        q = query.lower()
        return [
            d
            for d in self.list_documents()
            if q in d.title.lower() or q in d.file_name.lower()
        ]

    def clear_pipeline_data(self, doc_id: str) -> None:
        """Remove pipeline outputs for ``doc_id``, restoring the pre-pipeline state.

        Used before re-ingesting a document so the rerun does not hit
        UNIQUE constraints or consume stale document Markdown, and by the
        workspace "clear" action to revert a processed file to its imported
        state (source PDF + document record only).
        """
        from ...storage.sqlite.database import DatabaseManager

        backup_path = create_backup(self._root, doc_id, "pipeline_clear")
        db = DatabaseManager.get(str(self._root))
        with db.transaction() as (_kb_conn, mol_conn):
            DatabaseManager.delete_document_molecule_data(mol_conn, doc_id)

        resolver = self._layout
        paths = [
            resolver.document_md(doc_id),
            resolver.report_json(doc_id),
        ]
        dirs = [
            resolver.pages_dir(doc_id),
            resolver.crops_dir(doc_id),
            resolver.storage_dir(doc_id) / "artifacts",
            resolver.storage_dir(doc_id) / ".staging",
        ]
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Failed to remove %s during pipeline cleanup: %s", path, exc
                )
        for directory in dirs:
            if directory.exists():
                try:
                    shutil.rmtree(directory, ignore_errors=True)
                except OSError as exc:
                    logger.warning(
                        "Failed to remove %s for %s: %s", directory, doc_id, exc
                    )

        self.update_document_status(doc_id, "pending")
        logger.info("Pipeline data cleared: %s (backup=%s)", doc_id, backup_path)

    def update_document_status(self, doc_id: str, status: str) -> None:
        """Update the document status in its JSON record."""
        doc = load_document(doc_id, self._root)
        if doc is not None:
            doc._status = status
            save_document(doc)

    # ── File resolution ──────────────────────────────────────────

    def resolve_file(self, doc_id: str) -> str | None:
        """Resolve the original source file path for a document."""
        doc = load_document(doc_id, self._root)
        if doc is None:
            return None
        pdf_path = self._layout.storage_dir(doc_id) / doc.file_name
        return str(pdf_path) if pdf_path.exists() else None

    def doc_count(self) -> int:
        return len(self.list_documents())

    # ── Internals ────────────────────────────────────────────────

    def _require_doc(self, doc_id: str) -> None:
        """Raise ``NotFoundError`` if no JSON record exists for *doc_id*."""
        if load_document(doc_id, self._root) is None:
            raise NotFoundError(
                "Document not found",
                detail=f"doc_id={doc_id}",
            )


# ── Upload transport limits ──────────────────────────────────────

# 200 MB cap on browser uploads. Large PDFs should be imported from the
# filesystem or streamed; keeping the cap prevents OOM on malicious clients.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class DocumentNotFoundError(MBForgeError):
    status_code = 404
    error_code = "document_not_found"


class UploadTooLargeError(MBForgeError):
    status_code = 413
    error_code = "upload_too_large"


def ensure_writable_root(root: str) -> None:
    """Create the library root directory (validating writability)."""
    Path(root).mkdir(parents=True, exist_ok=True)


def create_upload_tmpfile(root: str) -> Path:
    """Create an OS-level temp file for a streamed upload.

    Uses the system temp directory instead of a ``{library_root}/tmp/``
    folder so the library root stays free of transient scratch files.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as tmp:
        return Path(tmp.name)


def add_uploaded_file(
    store: LibraryStore, tmp_path: Path, safe_name: str, title: str
) -> Document:
    """Register an uploaded file already streamed to ``tmp_path``."""
    return store.add_uploaded_file_from_path(tmp_path, safe_name, title)


# ── Document artifact reads ──────────────────────────────────────


def read_document_markdown(root: str, doc_id: str) -> str:
    """Read the canonical ``document.md`` for a document."""
    p = LibraryLayout(root).storage_dir(doc_id) / "document.md"
    if not p.is_file():
        logger.error(f"document.md not found for {doc_id}")
        return "document.md not found run pipeline first"
    return p.read_text(encoding="utf-8")


def read_document_report(root: str, doc_id: str) -> bytes:
    """Read the pipeline ``report.json`` for a document."""
    p = LibraryLayout(root).storage_dir(doc_id) / "report.json"
    if not p.is_file():
        raise NotFoundError(f"report.json not found for {doc_id}")
    return p.read_bytes()


def read_patent_facts(root: str, doc_id: str) -> bytes:
    """Read the Patent-stage facts artifact for a document."""
    p = LibraryLayout(root).storage_dir(doc_id) / "patent_facts.json"
    if not p.is_file():
        raise NotFoundError(f"patent_facts.json not found for {doc_id}")
    return p.read_bytes()


def read_page_text(root: str, doc_id: str, page: int) -> str:
    """Return the per-page OCR text for a single page (1-based).

    Routed through ``load_page_json`` so page artifacts have a single
    reader; missing or unparseable pages raise ``NotFoundError``.
    """
    from ...pipeline.extract.ocr_artifacts import load_page_json

    data = load_page_json(doc_id, root, page)
    if data is None:
        raise NotFoundError(f"page {page} text not found for {doc_id}")
    return data.get("text", "")


def resolve_document_pdf(root: str, doc_id: str) -> str:
    """Resolve the canonical PDF path with a legacy-layout fallback."""
    store = LibraryStore.get(root)
    pdf_path = store.resolve_file(doc_id)
    if pdf_path is None:
        # Fallback for legacy/project documents stored under
        # ``storage/{doc_id}/source.pdf`` but not yet registered in the
        # unified LibraryStore DB (e.g. pre-migration patents referenced
        # by their publication number).
        legacy_pdf = LibraryLayout(root).source_pdf(doc_id)
        if legacy_pdf.is_file():
            return str(legacy_pdf)
        raise DocumentNotFoundError(
            "Document file not found", detail=f"doc_id={doc_id}"
        )
    return pdf_path


def resolve_crop_path(root: str, doc_id: str, rel_path: str) -> Path:
    """Resolve a crop artifact path safely, raising when absent."""
    target = LibraryLayout(root).crop(doc_id, rel_path)
    if not target.is_file():
        raise NotFoundError(f"crop not found: {rel_path}")
    return target

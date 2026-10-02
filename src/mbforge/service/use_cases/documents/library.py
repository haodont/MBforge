"""LibraryStore — unified data store for the document library.

Document records live in the SQLite ``documents`` table; the source PDFs live at
``storage/{doc_id}/{file_name}``. ``doc_id`` is the SHA-256 hex digest of the
file bytes, so identical content always maps to one document, and ``file_name``
is unique, so two documents may not share a name.
"""

from __future__ import annotations

import functools
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from mbforge.domain.document import Document
from mbforge.foundation.errors import ConflictError, MBForgeError, NotFoundError
from mbforge.foundation.files import ensure_dir, sha256_file
from mbforge.foundation.layout import LibraryLayout, sanitize_upload_filename
from mbforge.foundation.logger import get_logger
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.backup import create_backup

logger = get_logger("mbforge.service.use_cases.documents.library")


class DuplicateDocumentNameError(ConflictError):
    error_code = "duplicate_filename"


def _now() -> str:
    """Return the timestamp format the rest of the schema uses."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class LibraryStore:
    """Single-library data store — documents, collections, and molecules."""

    def __init__(self, library_root: str | Path) -> None:
        self._root = Path(library_root).resolve()
        self._layout = LibraryLayout(self._root)
        # ponytail: serializes registrations per library; use per-name locks if
        # import concurrency becomes a bottleneck.
        self._registration_lock = Lock()

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
        with self._registration_lock:
            return self._register(src, src.name, title, move=False)

    def add_uploaded_file_from_path(
        self, src_path: str | Path, filename: str, title: str = ""
    ) -> Document:
        """Register a browser upload already streamed to ``src_path``.

        When the bytes are new the file is *moved* into storage, so ``src_path``
        is gone once this returns and the caller's cleanup becomes a no-op; on
        the duplicate-content path the file is left for the caller to remove.
        The content is never held in memory: the document id comes from hashing
        the streamed file.
        """
        src = Path(src_path)
        if not src.is_file():
            raise NotFoundError("Source file not found", detail=str(src))
        with self._registration_lock:
            return self._register(src, filename, title, move=True)

    def _register(
        self, src: Path, filename: str, title: str, *, move: bool
    ) -> Document:
        """Hash ``src``, store it under ``storage/{doc_id}/`` and register it.

        ``doc_id`` is the content address, so identical bytes that are already
        registered are returned as-is instead of being stored a second time.
        """
        safe_filename = sanitize_upload_filename(filename)
        doc_id = sha256_file(src)
        documents = get_repositories(self._root).documents
        existing = documents.get(doc_id)
        if existing is not None:
            logger.info(
                "Duplicate content; returning existing document %s (id=%s)",
                existing["file_name"],
                doc_id,
            )
            return Document.from_dict(existing, self._root)

        # Report a duplicate name with the API's error before touching disk;
        # the UNIQUE(file_name) constraint remains the authoritative guard.
        self._ensure_pdf_filename_available(safe_filename)

        safe_title = title.strip() if title else Path(safe_filename).stem
        storage_subdir = self._layout.storage_dir(doc_id)
        dest = storage_subdir / safe_filename
        try:
            ensure_dir(storage_subdir)
            if move:
                shutil.move(str(src), str(dest))
            else:
                shutil.copy2(str(src), str(dest))
        except (OSError, PermissionError) as e:
            self._discard_stored_file(dest, storage_subdir)
            raise MBForgeError("Failed to store file", detail=str(e)) from e

        doc = Document(
            doc_id=doc_id,
            library_root=self._root,
            title=safe_title,
            file_name=safe_filename,
            status="pending",
            created_at=_now(),
        )
        # Probe only the page count: an xref-only read, cheap enough for the
        # import path, and the document list renders it. Text, spans and layout
        # are produced by the Extract stage.
        get_repositories(self._root).artifacts.read_pdf_page_count(doc)
        try:
            documents.insert(doc.to_dict())
        except ConflictError:
            # Lost a race on file_name: drop the copy we just stored.
            self._discard_stored_file(dest, storage_subdir)
            raise
        logger.info("Document added: %s (id=%s)", safe_title, doc_id)
        return doc

    @staticmethod
    def _discard_stored_file(dest: Path, storage_subdir: Path) -> None:
        """Remove a partially stored file and its now-empty document dir."""
        if dest.exists():
            dest.unlink(missing_ok=True)
        if storage_subdir.exists() and not any(storage_subdir.iterdir()):
            storage_subdir.rmdir()

    def _ensure_pdf_filename_available(self, filename: str) -> None:
        if Path(filename).suffix.casefold() != ".pdf":
            return
        if get_repositories(self._root).documents.find_by_filename(filename):
            raise DuplicateDocumentNameError(
                f"A PDF named {filename!r} already exists in the library",
                detail=filename,
            )

    def load_document(self, doc_id: str) -> Document | None:
        """Load a Document from the registry.  ``None`` if absent."""
        row = get_repositories(self._root).documents.get(doc_id)
        return Document.from_dict(row, self._root) if row is not None else None

    def get_document(self, doc_id: str) -> Document | None:
        """Return the :class:`Document` entity for ``doc_id`` (``None`` if absent)."""
        return self.load_document(doc_id)

    def delete_document(self, doc_id: str) -> None:
        """Remove storage dir + registry row + molecule data."""
        backup_path = create_backup(self._root, doc_id, "document_delete")
        storage_subdir = self._layout.storage_dir(doc_id)
        if storage_subdir.exists():
            shutil.rmtree(storage_subdir, ignore_errors=True)

        from mbforge.service.ports import get_database

        db = get_database(str(self._root))
        with db.transaction() as (_kb_conn, mol_conn):
            db.delete_document_molecule_data(mol_conn, doc_id)
        get_repositories(self._root).documents.delete(doc_id)
        logger.info("Document deleted: %s (backup=%s)", doc_id, backup_path)

    def list_documents(self) -> list[Document]:
        """Return every registered document, newest first."""
        return [
            Document.from_dict(row, self._root)
            for row in get_repositories(self._root).documents.list_rows()
        ]

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
        from mbforge.service.ports import get_database

        backup_path = create_backup(self._root, doc_id, "pipeline_clear")
        db = get_database(str(self._root))
        with db.transaction() as (_kb_conn, mol_conn):
            db.delete_document_molecule_data(mol_conn, doc_id)

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
        """Update the document status in the registry."""
        get_repositories(self._root).documents.update_status(doc_id, status)

    # ── File resolution ──────────────────────────────────────────

    def resolve_file(self, doc_id: str) -> str | None:
        """Resolve the original source file path for a document."""
        doc = self.load_document(doc_id)
        if doc is None:
            return None
        pdf_path = self._layout.storage_dir(doc_id) / doc.file_name
        return str(pdf_path) if pdf_path.exists() else None

    def doc_count(self) -> int:
        return get_repositories(self._root).documents.count()


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
    from mbforge.service.pipeline.extract.ocr_artifacts import load_page_json

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

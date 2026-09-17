"""LibraryLayout — single authority for all library paths.

Resolves both **library-level** paths (``.mbforge/``, ``storage/``, ``notes/``)
and **document-level** artifact paths (``storage/{doc_id}/source.pdf``, etc.).
All file reads / writes that touch a path under the library root go through
this class so the storage layout is defined in one place and path traversal
attacks are rejected at a single chokepoint.

Layout (under ``{library_root}``):

Library-level:

* ``.mbforge/``                   — internal metadata root; never user-edited.
* ``.mbforge/library.db``         — unified business + molecule database.
* ``notes/``                      — user-editable notes.
* ``storage/``                    — document artifact root.

Document-level (under ``storage/{doc_id}/``):

* ``source.pdf``                  — original imported PDF bytes
* ``document.md``                 — canonical document Markdown
* ``document.json``               — document record (JSON)
* ``report.json``                 — pipeline report
* ``pages/page_{n:04d}.json``     — per-page OCR result (text + metadata)
* ``crops/{filename}``            — molecule crop images
* ``images/{filename}``           — figures extracted by OCR

No module is allowed to inline-construct these paths.

See ``docs/adr/0001-canonical-library-layout.md`` §2 + §3 for the
authoritative layout decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils import config
from ..utils.errors import MBForgeError, PathTraversalError  # noqa: F401 — re-export

# Safe doc_id: letters, digits, underscore, hyphen.
_SAFE_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
# run_id is generated as lowercase hex (uuid4.hex); accept the same charset
# as doc_id so legacy/derived IDs remain usable.
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


class InvalidDocIdError(ValueError):
    """Raised when ``doc_id`` fails the safety regex."""


# ── Library root probe ─────────────────────────────────────────────


@dataclass(frozen=True)
class LibraryWriteProbe:
    """Filesystem probe result for a configured library root."""

    configured: bool
    path: Path | None = None
    exists: bool = False
    writable: bool = False
    error: str | None = None


def probe_library_root(library_root: str | Path | None) -> LibraryWriteProbe:
    """Check whether a library root exists and accepts a marker write."""
    if not library_root:
        return LibraryWriteProbe(configured=False)

    layout = LibraryLayout(library_root)
    path = layout.library_root
    if not path.is_dir():
        return LibraryWriteProbe(
            configured=True,
            path=path,
            exists=False,
            error="directory does not exist",
        )
    try:
        layout.ensure_metadata_dir()
        layout.write_test_path.write_text("ok", encoding="utf-8")
        layout.write_test_path.unlink()
    except OSError as exc:
        return LibraryWriteProbe(
            configured=True,
            path=path,
            exists=True,
            error=str(exc)[:300],
        )
    return LibraryWriteProbe(
        configured=True,
        path=path,
        exists=True,
        writable=True,
    )


# ── LibraryLayout ──────────────────────────────────────────────────


class LibraryLayout:
    """Resolve all library paths — library-level and document-level.

    Stateless: constructing multiple instances for the same root is
    cheap and the resolver never touches the filesystem in its
    accessors. Use the ``ensure_*`` methods to create directories.
    """

    def __init__(self, library_root: str | Path) -> None:
        self._root = Path(library_root).expanduser().resolve()

    @property
    def library_root(self) -> Path:
        """Return the canonical absolute library root."""
        return self._root

    # -- Internal helpers -----------------------------------------------

    def _validate_and_join(self, *parts: str) -> Path:
        doc_id = parts[-1]
        if not doc_id or not _SAFE_DOC_ID_RE.match(doc_id):
            raise InvalidDocIdError(f"invalid doc_id: {doc_id!r}")
        return self._root.joinpath(*parts)

    def _doc_file(self, doc_id: str, name: str) -> Path:
        """Shortcut: ``storage/{doc_id}/{name}``."""
        return self.storage_dir(doc_id) / name

    def _ensure_dir(self, path: Path) -> Path:
        """Create *path* (and parents) if missing, then return it."""
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _safe_child(parent: Path, filename: str, *, label: str) -> Path:
        """Resolve *filename* under *parent* with traversal protection."""
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or filename.startswith("..")
            or filename in (".", "..")
        ):
            raise PathTraversalError(f"invalid {label}: {filename!r}")
        resolved = (parent / filename).resolve()
        try:
            resolved.relative_to(parent.resolve())
        except ValueError as exc:
            raise PathTraversalError(
                f"{label} path escapes parent dir: {filename}"
            ) from exc
        return resolved

    # -- Library-level paths -------------------------------------------

    @property
    def metadata_dir(self) -> Path:
        """``{root}/.mbforge/`` — internal metadata root.

        Users do not edit this directly. Library-level bookkeeping
        (unified database, knowledge index) lives here.
        """
        return self._root / ".mbforge"

    @property
    def storage_root(self) -> Path:
        """``{root}/storage/`` — canonical document artifact root."""
        return self._root / "storage"

    @property
    def write_test_path(self) -> Path:
        """Temporary marker used to verify that a library is writable."""
        return self.metadata_dir / ".write_test"

    @property
    def database_path(self) -> Path:
        """``{root}/.mbforge/library.db`` — unified business + molecule db."""
        return self.metadata_dir / "library.db"

    @property
    def notes_dir(self) -> Path:
        """``{root}/notes/`` — user-editable notes.

        This is the *only* library-level path users are expected to
        hand-edit or back up themselves. Everything else under
        ``.mbforge/`` is internal state.
        """
        return self._root / "notes"

    def ensure_metadata_dir(self) -> Path:
        """Create ``.mbforge/`` if missing and return the path."""
        return self._ensure_dir(self.metadata_dir)

    def ensure_notes_dir(self) -> Path:
        """Create ``notes/`` if missing and return the path."""
        return self._ensure_dir(self.notes_dir)

    def resolve_relative_path(self, relative_path: str | Path) -> Path:
        """Resolve a relative library path and enforce root containment."""
        candidate = Path(relative_path)
        if candidate.is_absolute() or any(
            part in (".", "..") for part in candidate.parts
        ):
            raise ValueError(f"invalid library-relative path: {relative_path}")
        resolved = (self._root / candidate).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(f"path escapes library root: {relative_path}") from exc
        return resolved

    # -- Document-level paths ------------------------------------------

    def storage_dir(self, doc_id: str) -> Path:
        """Return ``{root}/storage/{doc_id}`` (canonical storage subdir)."""
        return self._validate_and_join("storage", doc_id)

    def source_pdf(self, doc_id: str) -> Path:
        return self._doc_file(doc_id, "source.pdf")

    def document_md(self, doc_id: str) -> Path:
        return self._doc_file(doc_id, "document.md")

    def report_json(self, doc_id: str) -> Path:
        return self._doc_file(doc_id, "report.json")

    def pages_dir(self, doc_id: str) -> Path:
        return self._doc_file(doc_id, "pages")

    def page_text(self, doc_id: str, page: int) -> Path:
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        return self.pages_dir(doc_id) / f"page_{int(page):04d}.json"

    def crops_dir(self, doc_id: str) -> Path:
        return self._doc_file(doc_id, "crops")

    def artifacts_dir(self, doc_id: str) -> Path:
        """Return ``storage/{doc_id}/artifacts/`` (per-stage state artifacts).

        Canonical and readable; survives staging cleanup so a stage can
        hydrate pipeline context across separate ``run_pipeline`` calls.
        """
        return self._doc_file(doc_id, "artifacts")

    def runs_dir(self, doc_id: str) -> Path:
        """Return ``storage/{doc_id}/runs/`` (published pipeline runs)."""
        return self._doc_file(doc_id, "runs")

    def run_dir(self, doc_id: str, run_id: str) -> Path:
        """Return ``storage/{doc_id}/runs/{run_id}/`` for a published run."""
        if not run_id or not _SAFE_RUN_ID_RE.match(run_id):
            raise ValueError(f"invalid run_id: {run_id!r}")
        return self.runs_dir(doc_id) / run_id

    def run_current_json(self, doc_id: str) -> Path:
        """Return ``storage/{doc_id}/runs/current.json`` (published-run pointer)."""
        return self.runs_dir(doc_id) / "current.json"

    def crop(self, doc_id: str, relpath: str) -> Path:
        """Resolve a crop filename to a path under ``storage/{doc_id}/crops/``.

        Historical pipelines stored absolute paths in ``image_path``; the
        endpoint normalises them to their basename before serving.
        """
        if not relpath or ".." in relpath.replace("\\", "/").split("/"):
            raise PathTraversalError(f"invalid crop relpath: {relpath!r}")
        # Extract basename for legacy absolute-path compatibility.
        name = relpath.replace("\\", "/").rsplit("/", 1)[-1]
        parent = self.crops_dir(doc_id)
        target = (parent / name).resolve()
        try:
            target.relative_to(parent.resolve())
        except ValueError as exc:
            raise PathTraversalError(f"crop path escapes crops dir: {relpath}") from exc
        return target


# ── Library root resolution ────────────────────────────────────────


class InvalidPathError(MBForgeError):
    """Raised when a request path is empty, malformed, or escapes the library."""

    status_code = 400
    error_code = "invalid_path"


_SAFE_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def validate_doc_id(doc_id: str) -> None:
    """Raise ``InvalidPathError`` if ``doc_id`` is empty or contains separators."""
    if not doc_id or not _SAFE_DOC_ID_RE.match(doc_id):
        raise InvalidPathError(f"invalid doc_id: {doc_id!r}")


def canonicalize_library_root(library_root: str | Path) -> Path:
    """Return one absolute, normalized library root without I/O."""
    value = Path(library_root).expanduser()
    if not value.is_absolute():
        raise InvalidPathError(f"invalid library_root: {library_root}")
    return value.resolve()


def load_global_config():
    """Keep the historical patchable import while using the config module."""
    return config.load_global_config()


def resolve_library_root(
    library_root: str | Path | None = None, *, require_configured: bool = True
) -> Path:
    """Resolve the active library root to a canonical absolute path."""
    cfg_root = load_global_config().library_root or ""
    value = library_root or cfg_root
    if not value:
        raise InvalidPathError("library_root is required")
    resolved = canonicalize_library_root(value)
    if (
        require_configured
        and cfg_root
        and resolved != canonicalize_library_root(cfg_root)
    ):
        raise InvalidPathError(f"library_root does not match configured root: {value}")
    return resolved


def resolve_library_root_candidate(library_root: str | Path) -> Path:
    """Canonicalize a root before it becomes the configured active root."""
    return resolve_library_root(library_root, require_configured=False)


def extract_library_root(payload: dict[str, Any] | Any) -> str:
    """Read the canonical field, with one centralized legacy alias."""
    data = payload if isinstance(payload, dict) else payload.model_dump()
    return str(data.get("library_root") or data.get("libraryRoot") or "")


def resolve_root(body: dict[str, Any] | None = None) -> str:
    """Resolve library root from a request body or global config."""
    b = body or {}
    root = extract_library_root(b)
    if root:
        return str(resolve_library_root(root))
    cfg = load_global_config()
    if cfg.library_root:
        return str(resolve_library_root())
    return ""


@dataclass(frozen=True, slots=True)
class LibraryPathContext:
    """Canonical path context shared by routers and application services."""

    root: Path

    @classmethod
    def from_request(
        cls, payload: dict[str, Any] | Any, *, require_configured: bool = True
    ) -> LibraryPathContext:
        return cls(
            resolve_library_root(
                extract_library_root(payload) or None,
                require_configured=require_configured,
            )
        )

    @classmethod
    def from_root(
        cls, library_root: str | Path, *, require_configured: bool = False
    ) -> LibraryPathContext:
        return cls(
            resolve_library_root(library_root, require_configured=require_configured)
        )

    @property
    def layout(self) -> LibraryLayout:
        return LibraryLayout(self.root)


def sanitize_upload_filename(filename: str) -> str:
    """Return a safe upload filename.

    Rejects empty names and any path segment that is ``.`` or ``..`` after
    splitting on ``/`` and ``\\``. All other names are reduced to their final
    segment, so names like ``report..pdf`` are allowed but ``../passwd`` is
    rejected.
    """
    if not filename:
        raise InvalidPathError("filename is required")

    segments = re.split(r"[/\\]", filename)
    if any(seg in (".", "..") for seg in segments):
        raise InvalidPathError(f"filename contains path traversal: {filename!r}")

    safe = filename.replace("\\", "/").split("/")[-1]
    if not safe or safe in (".", ".."):
        raise InvalidPathError(f"invalid filename: {filename!r}")
    return safe

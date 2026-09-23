"""Repository ports for application use cases.

The application layer receives these contracts from the composition root.  A
use case may ask for a repository for a library, but it never constructs a
SQLite connection or imports a persistence adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from mbforge.domain.evidence import SourceEvidence


@runtime_checkable
class DatabaseRepository(Protocol):
    """The library database boundary exposed to application code.

    Existing use cases still need a small set of transaction and connection
    operations while they are being split into aggregate repositories.  The
    concrete adapter owns the connection implementation and exposes these
    operations through this protocol instead of leaking ``DatabaseManager``.
    """

    def initialize(self) -> None: ...

    def kb_conn(self) -> Any: ...

    def mol_conn(self) -> Any: ...

    def transaction(self, db: str = "kb") -> Any: ...

    def execute(
        self, sql: str, params: Sequence[Any] = (), *, db: str = "kb"
    ) -> Any: ...

    def __getattr__(self, name: str) -> Any: ...


class EvidenceRepository(Protocol):
    """Canonical SourceEvidence persistence contract."""

    def persist(self, evidence: Sequence[SourceEvidence] | object) -> int: ...


class MarkushRepository(Protocol):
    """Markush review persistence contract."""

    def list_candidates(self, conn: Any, **kwargs: Any) -> Any: ...

    def get_candidate_detail(self, conn: Any, candidate_id: str) -> Any: ...

    def update_candidate(self, conn: Any, **kwargs: Any) -> Any: ...


class ReviewRepository(Protocol):
    """Persistence boundary for native and Markush review records."""

    def insert_review_item(self, conn: Any, **kwargs: Any) -> str: ...

    def record_review_decision(self, conn: Any, **kwargs: Any) -> None: ...

    def persist_review_candidates(
        self,
        doc_id: str,
        candidates: Any,
        conn: Any,
        recognition_version: int = 1,
    ) -> int: ...

    def fetch_one(self, conn: Any, sql: str, params: Any) -> Any: ...

    def copy_evidence(
        self, conn: Any, row: Any, entity_type: str, entity_id: str, doc_id: str
    ) -> None: ...


class ArtifactStore(Protocol):
    """Filesystem artifact contract for document records and PDF caches."""

    def load_document(self, doc_id: str, library_root: str | Path) -> Any: ...

    def save_document(self, document: Any) -> None: ...

    def extract_pdf_text(self, document: Any) -> str: ...


class LibraryRepositories(Protocol):
    """Aggregate repository collection for one library root."""

    @property
    def database(self) -> DatabaseRepository: ...

    @property
    def evidence(self) -> EvidenceRepository: ...

    @property
    def markush(self) -> MarkushRepository: ...

    @property
    def review(self) -> ReviewRepository: ...

    @property
    def artifacts(self) -> ArtifactStore: ...


RepositoryFactory = Callable[[str | Path], LibraryRepositories]

_factory: RepositoryFactory | None = None


def configure_repository_factory(factory: RepositoryFactory) -> None:
    """Install the adapter factory during application composition."""

    global _factory
    _factory = factory


def get_repositories(library_root: str | Path) -> LibraryRepositories:
    """Return repositories for *library_root*.

    Failing closed here makes an incorrectly assembled application obvious at
    startup instead of silently constructing a second persistence stack.
    """

    if _factory is None:
        raise RuntimeError(
            "repository factory is not configured; build the application "
            "through mbforge.app or configure it in the test composition root"
        )
    return _factory(library_root)


def get_database(library_root: str | Path) -> DatabaseRepository:
    """Return the database repository for *library_root*."""

    return get_repositories(library_root).database


__all__ = [
    "DatabaseRepository",
    "ArtifactStore",
    "EvidenceRepository",
    "LibraryRepositories",
    "MarkushRepository",
    "ReviewRepository",
    "RepositoryFactory",
    "configure_repository_factory",
    "get_database",
    "get_repositories",
]

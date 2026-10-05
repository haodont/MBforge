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
from mbforge.service.dto.molecule import MoleculeListRequest


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

    def snapshot_document(self, doc_id: str) -> dict[str, Any]: ...

    def __getattr__(self, name: str) -> Any: ...


class EvidenceRepository(Protocol):
    """Canonical SourceEvidence persistence and read contract."""

    def persist(
        self, evidence: Sequence[SourceEvidence] | object, conn: Any = None
    ) -> int: ...

    def get(self, evidence_id: str) -> SourceEvidence | None: ...

    def list(
        self,
        doc_id: str,
        *,
        page: int | None = None,
        kind: str | None = None,
    ) -> list[SourceEvidence]: ...

    def at(
        self, doc_id: str, page: int, bbox: tuple[float, float, float, float]
    ) -> list[SourceEvidence]: ...

    def molecule_metadata(
        self, evidence_id: str, doc_id: str
    ) -> tuple[str, str] | None: ...

    def update_molecule_raw_text(
        self, evidence_id: str, doc_id: str, raw_text: str
    ) -> int: ...


class MoleculeRepository(Protocol):
    """Molecule catalog persistence: list, CRUD, search, corrections."""

    def list_page(self, request: MoleculeListRequest) -> dict[str, Any]: ...

    def get_row(self, mol_id: str) -> dict[str, Any] | None: ...

    def find_row(self, canonical_smiles: str) -> dict[str, Any] | None: ...

    def create(
        self,
        mol_id: str,
        smiles: str,
        esmiles: str | None,
        name: str | None,
        source_type: str | None,
    ) -> None: ...

    def bulk_update_status(self, mol_ids: Sequence[str], status: str) -> int: ...

    def update(self, mol_id: str, updates: dict[str, Any]) -> None: ...

    def list_corrections(self, mol_id: str) -> list[dict[str, Any]]: ...

    def delete(self, mol_ids: Sequence[str]) -> int: ...

    def stats(self) -> dict[str, Any]: ...

    def search_text(self, query: str, top_k: int) -> list[dict[str, Any]]: ...

    def search_substructure(
        self, query_smiles: str, top_k: int
    ) -> list[dict[str, Any]]: ...

    def search_similarity(
        self, query_smiles: str, top_k: int, threshold: float
    ) -> list[dict[str, Any]]: ...

    def detection_cache_matches(
        self, doc_id: str, page: int, query_box: tuple[float, float, float, float]
    ) -> list[dict[str, Any]]: ...

    def identity_fields(self, mol_ids: Sequence[str]) -> dict[str, dict[str, Any]]: ...

    def list_molecule_evidence(
        self, canonical_smiles: Sequence[str]
    ) -> list[dict[str, Any]]: ...

    def evidence_for_molecules(
        self, mol_ids: Sequence[str], canonicals: Sequence[str]
    ) -> list[dict[str, Any]]: ...

    def load_detections(
        self, doc_id: str, page: int | None = None
    ) -> list[dict[str, Any]]: ...

    def save_detections(self, detections: Sequence[dict[str, Any]]) -> None: ...

    def detection_counts(self) -> tuple[int, int]: ...

    def clear_detections(self, doc_id: str | None = None) -> int: ...

    def molecules_for_recorrection(
        self, doc_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    def detections_for_molecules(
        self, mol_ids: Sequence[str]
    ) -> list[dict[str, Any]]: ...

    def apply_corrections(self, updates: Sequence[dict[str, Any]]) -> None: ...

    def persist_candidates(self, doc_id: str, candidates: Sequence[Any]) -> int: ...

    def replace_document_candidates(
        self,
        doc_id: str,
        candidates: Sequence[Any],
        activity_updates: Sequence[dict[str, Any]] | None = None,
    ) -> int: ...


class ActivityRepository(Protocol):
    """Persistence boundary for the ``activities`` table and activity reviews."""

    def list_activities(
        self,
        doc_id: str,
        *,
        target: str = "",
        assay_description: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def list_activity_review_items(
        self, doc_id: str, limit: int
    ) -> list[dict[str, Any]]: ...


class CollectionRepository(Protocol):
    """Persistence boundary for user collections ("Groups")."""

    def create(
        self, collection_id: str, name: str, parent_id: str | None = None
    ) -> None: ...

    def rename(self, collection_id: str, name: str) -> None: ...

    def list_rows(self) -> list[dict[str, Any]]: ...

    def counts(self) -> dict[str, int]: ...

    def delete(self, collection_id: str) -> None: ...

    def add_document(self, collection_id: str, doc_id: str) -> None: ...

    def remove_document(self, collection_id: str, doc_id: str) -> None: ...


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

    def list_queue(
        self,
        conn: Any,
        *,
        kind: str | None = None,
        status: str | None = None,
        doc_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def get_item(self, conn: Any, kind: str, item_id: str) -> dict[str, Any]: ...

    def stats(self, conn: Any) -> dict[str, Any]: ...

    def history(
        self, conn: Any, entity_id: str
    ) -> tuple[str, list[dict[str, Any]]]: ...

    def markush_candidate_version(self, conn: Any, item_id: str) -> int | None: ...

    def review_item_status_payload(
        self, conn: Any, item_id: str, kind: str
    ) -> dict[str, Any] | None: ...

    def set_review_item_status(
        self, conn: Any, item_id: str, kind: str, new_status: str
    ) -> None: ...

    def set_molecule_review_status(
        self, conn: Any, mol_id: str, status: str
    ) -> None: ...

    def set_molecule_name(self, conn: Any, mol_id: str, name: str) -> None: ...

    def clear_all(self, conn: Any) -> dict[str, int]: ...


class ArtifactStore(Protocol):
    """Filesystem artifact contract for document source files."""

    def read_pdf_page_count(self, document: Any) -> int: ...


class DocumentRepository(Protocol):
    """Document-registry contract: one row per stored document.

    ``doc_id`` is the content address (SHA-256 of the file bytes) and
    ``file_name`` is unique, so the registry itself enforces both dedup by
    content and rejection of duplicate names.
    """

    def insert(self, record: dict[str, Any]) -> None: ...

    def get(self, doc_id: str) -> dict[str, Any] | None: ...

    def find_by_filename(self, file_name: str) -> dict[str, Any] | None: ...

    def list_rows(
        self, *, statuses: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return document rows, optionally restricted to *statuses*."""
        ...

    def count(self, *, statuses: Sequence[str] | None = None) -> int: ...

    def update_status(self, doc_id: str, status: str) -> None: ...

    def delete_many(self, doc_ids: Sequence[str]) -> None: ...


class LibraryRepositories(Protocol):
    """Aggregate repository collection for one library root."""

    @property
    def database(self) -> DatabaseRepository: ...

    @property
    def documents(self) -> DocumentRepository: ...

    @property
    def evidence(self) -> EvidenceRepository: ...

    @property
    def molecules(self) -> MoleculeRepository: ...

    @property
    def activities(self) -> ActivityRepository: ...

    @property
    def collections(self) -> CollectionRepository: ...

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
            "through mbforge.server.app or configure it in the test composition root"
        )
    return _factory(library_root)


def get_database(library_root: str | Path) -> DatabaseRepository:
    """Return the database repository for *library_root*."""

    return get_repositories(library_root).database


__all__ = [
    "DatabaseRepository",
    "ArtifactStore",
    "DocumentRepository",
    "EvidenceRepository",
    "LibraryRepositories",
    "MarkushRepository",
    "MoleculeRepository",
    "ReviewRepository",
    "RepositoryFactory",
    "configure_repository_factory",
    "get_database",
    "get_repositories",
]

"""SQLite repository implementations.

This module is the only application-facing construction point for the legacy
``DatabaseManager``.  Use cases receive the small repository port instead of
importing the concrete manager directly.  The manager remains here because it
still contains the schema and connection lifecycle implementation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mbforge.adapters.persistence import markush_transitions, source_evidence
from mbforge.adapters.persistence.markush_candidates import persist_review_candidates
from mbforge.adapters.persistence.markush_transitions import (
    _copy_evidence,
    _fetch_one,
)
from mbforge.adapters.persistence.review_audit import (
    insert_review_item,
    record_review_decision,
)
from mbforge.adapters.persistence.sqlite.database import (
    DatabaseManager,
    record_ingest_event,
)
from mbforge.application.ports.repositories import (
    DatabaseRepository,
    LibraryRepositories,
)
from mbforge.domain.evidence import SourceEvidence


@dataclass
class SqliteDatabaseRepository:
    """Repository facade over one library's unified SQLite database."""

    _manager: DatabaseManager

    def initialize(self) -> None:
        self._manager.initialize()

    def kb_conn(self) -> Any:
        return self._manager.kb_conn()

    def mol_conn(self) -> Any:
        return self._manager.mol_conn()

    def transaction(self, db: str = "kb") -> Any:
        # The legacy manager now exposes one unified database transaction;
        # keep the optional argument for callers that still pass ``db``.
        return self._manager.transaction()

    def execute(self, sql: str, params: Sequence[Any] = (), *, db: str = "kb") -> Any:
        return self._manager.execute(sql, params, db=db)

    def delete_molecule_records(self, conn: Any, mol_ids: Iterable[str]) -> int:
        return DatabaseManager.delete_molecule_records(conn, mol_ids)

    def delete_molecule_from_mol_search(self, conn: Any, mol_id: str) -> None:
        DatabaseManager.delete_molecule_from_mol_search(conn, mol_id)

    def sync_molecule_to_mol_search(self, conn: Any, mol_id: str) -> None:
        DatabaseManager.sync_molecule_to_mol_search(conn, mol_id)

    def sync_molecule_fingerprint(self, conn: Any, mol_id: str) -> None:
        DatabaseManager.sync_molecule_fingerprint(conn, mol_id)

    def delete_document_molecule_data(self, conn: Any, doc_id: str) -> int:
        return DatabaseManager.delete_document_molecule_data(conn, doc_id)

    def record_ingest_event(self, **kwargs: Any) -> None:
        record_ingest_event(self._manager, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Keep the adapter surface compatible while methods are extracted."""

        return getattr(self._manager, name)


@dataclass
class SqliteEvidenceRepository:
    """Repository for the canonical joined SourceEvidence index."""

    library_root: Path

    def persist(self, evidence: Sequence[SourceEvidence] | object) -> int:
        return source_evidence.persist_source_evidence(self.library_root, evidence)


@dataclass
class SqliteMarkushRepository:
    """Repository facade for Markush review transitions."""

    def list_candidates(self, conn: Any, **kwargs: Any) -> Any:
        return markush_transitions.list_candidates(conn, **kwargs)

    def get_candidate_detail(self, conn: Any, candidate_id: str) -> Any:
        return markush_transitions.get_candidate_detail(conn, candidate_id)

    def update_candidate(self, conn: Any, **kwargs: Any) -> Any:
        return markush_transitions.update_candidate(conn, **kwargs)


@dataclass
class SqliteReviewRepository:
    """Repository facade for review queue and audit persistence."""

    def insert_review_item(self, conn: Any, **kwargs: Any) -> str:
        return insert_review_item(conn, **kwargs)

    def record_review_decision(self, conn: Any, **kwargs: Any) -> None:
        record_review_decision(conn, **kwargs)

    def persist_review_candidates(
        self,
        doc_id: str,
        candidates: Any,
        conn: Any,
        recognition_version: int = 1,
    ) -> int:
        return persist_review_candidates(
            doc_id,
            candidates,
            conn=conn,
            recognition_version=recognition_version,
        )

    def fetch_one(self, conn: Any, sql: str, params: Any) -> Any:
        return _fetch_one(conn, sql, params)

    def copy_evidence(
        self, conn: Any, row: Any, entity_type: str, entity_id: str, doc_id: str
    ) -> None:
        _copy_evidence(conn, row, entity_type, entity_id, doc_id)


@dataclass
class FilesystemArtifactStore:
    """Repository facade for document JSON and cached PDF extraction."""

    def load_document(self, doc_id: str, library_root: str | Path) -> Any:
        from mbforge.adapters.persistence.document_store import load_document

        return load_document(doc_id, library_root)

    def save_document(self, document: Any) -> None:
        from mbforge.adapters.persistence.document_store import save_document

        save_document(document)

    def extract_pdf_text(self, document: Any) -> str:
        from mbforge.adapters.persistence.document_store import extract_pdf_text

        return extract_pdf_text(document)


@dataclass
class SqliteRepositories(LibraryRepositories):
    """Repositories for one library root."""

    library_root: Path
    _database: SqliteDatabaseRepository
    _markush: SqliteMarkushRepository
    _review: SqliteReviewRepository
    _artifacts: FilesystemArtifactStore

    @property
    def database(self) -> DatabaseRepository:
        return self._database

    @property
    def evidence(self) -> SqliteEvidenceRepository:
        return SqliteEvidenceRepository(self.library_root)

    @property
    def markush(self) -> SqliteMarkushRepository:
        return self._markush

    @property
    def review(self) -> SqliteReviewRepository:
        return self._review

    @property
    def artifacts(self) -> FilesystemArtifactStore:
        return self._artifacts


def create_repositories(library_root: str | Path) -> SqliteRepositories:
    """Build the SQLite repository set for a library."""

    root = Path(library_root).expanduser().resolve()
    return SqliteRepositories(
        root,
        SqliteDatabaseRepository(DatabaseManager.get(root)),
        SqliteMarkushRepository(),
        SqliteReviewRepository(),
        FilesystemArtifactStore(),
    )


__all__ = [
    "SqliteDatabaseRepository",
    "SqliteEvidenceRepository",
    "SqliteRepositories",
    "SqliteMarkushRepository",
    "SqliteReviewRepository",
    "FilesystemArtifactStore",
    "create_repositories",
]

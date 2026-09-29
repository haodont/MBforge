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

from mbforge.db import (
    activity_store,
    collection_store,
    document_backup,
    evidence,
    markush_transitions,
    molecule_store,
    source_evidence,
)
from mbforge.db.markush_candidates import persist_review_candidates
from mbforge.db.markush_transitions import (
    _copy_evidence,
    _fetch_one,
)
from mbforge.db.review_audit import (
    insert_review_item,
    record_review_decision,
)
from mbforge.db.sqlite.database import (
    DatabaseManager,
    record_ingest_event,
)
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.ports.repositories import (
    DatabaseRepository,
    LibraryRepositories,
)


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

    def snapshot_document(self, doc_id: str) -> dict[str, Any]:
        return document_backup.snapshot_doc_db(self._manager, doc_id)

    def __getattr__(self, name: str) -> Any:
        """Keep the adapter surface compatible while methods are extracted."""

        return getattr(self._manager, name)


@dataclass
class SqliteEvidenceRepository:
    """Repository for the canonical SourceEvidence index."""

    library_root: Path

    def persist(self, evidence: Sequence[SourceEvidence] | object) -> int:
        return source_evidence.persist_source_evidence(self.library_root, evidence)

    def get(self, evidence_id: str) -> SourceEvidence | None:
        return source_evidence.get_source_evidence(self.library_root, evidence_id)

    def list(
        self,
        doc_id: str,
        *,
        page: int | None = None,
        kind: str | None = None,
    ) -> list[SourceEvidence]:
        return source_evidence.list_source_evidence(
            self.library_root, doc_id, page=page, kind=kind
        )

    def at(
        self, doc_id: str, page: int, bbox: tuple[float, float, float, float]
    ) -> list[SourceEvidence]:
        return source_evidence.source_evidence_at(self.library_root, doc_id, page, bbox)

    def list_molecule_evidence(
        self, canonical_smiles: Sequence[str]
    ) -> list[dict[str, Any]]:
        return evidence.list_molecule_evidence(self.library_root, canonical_smiles)

    def evidence_for_molecules(
        self, mol_ids: Sequence[str], canonicals: Sequence[str]
    ) -> list[dict[str, Any]]:
        return evidence.evidence_for_molecules(self.library_root, mol_ids, canonicals)

    def molecule_metadata(
        self, evidence_id: str, doc_id: str
    ) -> tuple[str, str] | None:
        return source_evidence.molecule_metadata(self.library_root, evidence_id, doc_id)

    def update_molecule_raw_text(
        self, evidence_id: str, doc_id: str, raw_text: str
    ) -> int:
        return source_evidence.update_molecule_raw_text(
            self.library_root, evidence_id, doc_id, raw_text
        )


@dataclass
class SqliteMoleculeRepository:
    """Repository for the molecule catalog (list, CRUD, search)."""

    library_root: Path

    def list_page(self, request: Any) -> dict[str, Any]:
        return molecule_store.list_page(self.library_root, request)

    def get_row(self, mol_id: str) -> dict[str, Any] | None:
        return molecule_store.get_row(self.library_root, mol_id)

    def find_row(self, canonical_smiles: str) -> dict[str, Any] | None:
        return molecule_store.find_row(self.library_root, canonical_smiles)

    def create(
        self,
        mol_id: str,
        smiles: str,
        esmiles: str | None,
        name: str | None,
        source_type: str | None,
    ) -> None:
        molecule_store.create(
            self.library_root, mol_id, smiles, esmiles, name, source_type
        )

    def bulk_update_status(self, mol_ids: Sequence[str], status: str) -> int:
        return molecule_store.bulk_update_status(self.library_root, mol_ids, status)

    def update(self, mol_id: str, updates: dict[str, Any]) -> None:
        molecule_store.update(self.library_root, mol_id, updates)

    def list_corrections(self, mol_id: str) -> list[dict[str, Any]]:
        return molecule_store.list_corrections(self.library_root, mol_id)

    def delete(self, mol_ids: Sequence[str]) -> int:
        return molecule_store.delete(self.library_root, mol_ids)

    def stats(self) -> dict[str, Any]:
        return molecule_store.stats(self.library_root)

    def search_text(self, query: str, top_k: int) -> list[dict[str, Any]]:
        return molecule_store.search_text(self.library_root, query, top_k)

    def search_substructure(
        self, query_smiles: str, top_k: int
    ) -> list[dict[str, Any]]:
        return molecule_store.search_substructure(
            self.library_root, query_smiles, top_k
        )

    def search_similarity(
        self, query_smiles: str, top_k: int, threshold: float
    ) -> list[dict[str, Any]]:
        return molecule_store.search_similarity(
            self.library_root, query_smiles, top_k, threshold
        )

    def detection_cache_matches(
        self, doc_id: str, page: int, query_box: tuple[float, float, float, float]
    ) -> list[dict[str, Any]]:
        return molecule_store.detection_cache_matches(
            self.library_root, doc_id, page, query_box
        )

    def identity_fields(self, mol_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        return molecule_store.identity_fields(self.library_root, mol_ids)

    def load_detections(
        self, doc_id: str, page: int | None = None
    ) -> list[dict[str, Any]]:
        return molecule_store.load_detections(self.library_root, doc_id, page)

    def save_detections(self, detections: Sequence[dict[str, Any]]) -> None:
        molecule_store.save_detections(self.library_root, detections)

    def detection_counts(self) -> tuple[int, int]:
        return molecule_store.detection_counts(self.library_root)

    def clear_detections(self, doc_id: str | None = None) -> int:
        return molecule_store.clear_detections(self.library_root, doc_id)

    def molecules_for_recorrection(
        self, doc_id: str | None = None
    ) -> list[dict[str, Any]]:
        return molecule_store.molecules_for_recorrection(self.library_root, doc_id)

    def detections_for_molecules(self, mol_ids: Sequence[str]) -> list[dict[str, Any]]:
        return molecule_store.detections_for_molecules(self.library_root, mol_ids)

    def apply_corrections(self, updates: Sequence[dict[str, Any]]) -> None:
        molecule_store.apply_corrections(self.library_root, updates)

    def persist_candidates(self, doc_id: str, candidates: Sequence[Any]) -> int:
        return molecule_store.persist_candidates(self.library_root, doc_id, candidates)

    def replace_document_candidates(
        self,
        doc_id: str,
        candidates: Sequence[Any],
        activity_updates: Sequence[dict[str, Any]] | None = None,
    ) -> int:
        return molecule_store.replace_document_candidates(
            self.library_root, doc_id, candidates, activity_updates
        )


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
class SqliteActivityRepository:
    """Repository for the ``activities`` table and activity review items."""

    library_root: Path

    def list_activities(
        self,
        doc_id: str,
        *,
        target: str = "",
        assay_description: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return activity_store.list_activities(
            self.library_root,
            doc_id,
            target=target,
            assay_description=assay_description,
            limit=limit,
        )

    def list_activity_review_items(
        self, doc_id: str, limit: int
    ) -> list[dict[str, Any]]:
        return activity_store.list_activity_review_items(
            self.library_root, doc_id, limit
        )


@dataclass
class SqliteCollectionRepository:
    """Repository for user collections ("Groups")."""

    library_root: Path

    def create(
        self, collection_id: str, name: str, parent_id: str | None = None
    ) -> None:
        collection_store.create(self.library_root, collection_id, name, parent_id)

    def rename(self, collection_id: str, name: str) -> None:
        collection_store.rename(self.library_root, collection_id, name)

    def list_rows(self) -> list[dict[str, Any]]:
        return collection_store.list_rows(self.library_root)

    def counts(self) -> dict[str, int]:
        return collection_store.counts(self.library_root)

    def delete(self, collection_id: str) -> None:
        collection_store.delete(self.library_root, collection_id)

    def add_document(self, collection_id: str, doc_id: str) -> None:
        collection_store.add_document(self.library_root, collection_id, doc_id)

    def remove_document(self, collection_id: str, doc_id: str) -> None:
        collection_store.remove_document(self.library_root, collection_id, doc_id)


@dataclass
class FilesystemArtifactStore:
    """Repository facade for document JSON and cached PDF extraction."""

    def load_document(self, doc_id: str, library_root: str | Path) -> Any:
        from mbforge.db.document_store import load_document

        return load_document(doc_id, library_root)

    def save_document(self, document: Any) -> None:
        from mbforge.db.document_store import save_document

        save_document(document)

    def extract_pdf_text(self, document: Any) -> str:
        from mbforge.db.document_store import extract_pdf_text

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
    def molecules(self) -> SqliteMoleculeRepository:
        return SqliteMoleculeRepository(self.library_root)

    @property
    def activities(self) -> SqliteActivityRepository:
        return SqliteActivityRepository(self.library_root)

    @property
    def collections(self) -> SqliteCollectionRepository:
        return SqliteCollectionRepository(self.library_root)

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
    "SqliteActivityRepository",
    "SqliteCollectionRepository",
    "SqliteDatabaseRepository",
    "SqliteEvidenceRepository",
    "SqliteRepositories",
    "SqliteMarkushRepository",
    "SqliteMoleculeRepository",
    "SqliteReviewRepository",
    "FilesystemArtifactStore",
    "create_repositories",
]

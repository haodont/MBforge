"""SQLite repository implementations.

This module is the only application-facing construction point for the legacy
``DatabaseManager``.  Use cases receive the small repository port instead of
importing the concrete manager directly.  The manager remains here because it
still contains the schema and connection lifecycle implementation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mbforge.contracts.measurement import (
    MeasurementDatasetStats,
    MeasurementQuery,
)
from mbforge.db import (
    detection_store,
    document_backup,
    document_records,
    label_anchor_store,
    measurement_store,
    molecule_candidates,
    molecule_store,
    patent_analysis_store,
    review_store,
    source_evidence,
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
from mbforge.domain.relation import LabelAnchor, PageGeometry
from mbforge.ports.repositories import (
    DatabaseRepository,
    LibraryRepositories,
)


@dataclass
class SqliteDatabaseRepository:
    """Repository facade over one library's unified SQLite database."""

    _manager: DatabaseManager

    def initialize(self) -> None:
        self._manager.initialize()

    def document_status_counts(self) -> dict[str, int]:
        """Count documents grouped by ``status``."""
        with self._manager.connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM documents GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["c"]) for row in rows}

    def ping(self) -> None:
        """Open (and initialize) the unified database connection."""
        with self._manager.connection():
            pass

    def delete_molecule_records(self, conn: Any, mol_ids: Iterable[str]) -> int:
        return DatabaseManager.delete_molecule_records(conn, mol_ids)

    def delete_molecule_from_mol_search(self, conn: Any, mol_id: str) -> None:
        DatabaseManager.delete_molecule_from_mol_search(conn, mol_id)

    def sync_molecule_to_mol_search(self, conn: Any, mol_id: str) -> None:
        DatabaseManager.sync_molecule_to_mol_search(conn, mol_id)

    def sync_molecule_fingerprint(self, conn: Any, mol_id: str) -> None:
        DatabaseManager.sync_molecule_fingerprint(conn, mol_id)

    def delete_document_molecule_data(self, doc_id: str) -> int:
        with self._manager.connection() as conn:
            return DatabaseManager.delete_document_molecule_data(conn, doc_id)

    def record_ingest_event(self, **kwargs: Any) -> None:
        record_ingest_event(self._manager, **kwargs)

    def snapshot_document(self, doc_id: str) -> dict[str, Any]:
        return document_backup.snapshot_doc_db(self._manager, doc_id)


@dataclass
class SqliteEvidenceRepository:
    """Repository for the canonical SourceEvidence index."""

    library_root: Path

    def persist(self, evidence: Sequence[SourceEvidence] | object) -> int:
        return source_evidence.persist_source_evidence(self.library_root, evidence)

    def get(self, evidence_id: str) -> SourceEvidence | None:
        return source_evidence.get_source_evidence(self.library_root, evidence_id)

    def search(
        self, query: str, *, doc_id: str = "", limit: int = 20, offset: int = 0
    ) -> list[dict[str, object]]:
        return source_evidence.search_source_evidence(
            self.library_root, query, doc_id=doc_id, limit=limit, offset=offset
        )

    def list(
        self,
        doc_id: str,
        *,
        page: int | None = None,
        kind: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SourceEvidence]:
        return source_evidence.list_source_evidence(
            self.library_root,
            doc_id,
            page=page,
            kind=kind,
            limit=limit,
            offset=offset,
        )

    def at(
        self, doc_id: str, page: int, bbox: tuple[float, float, float, float]
    ) -> list[SourceEvidence]:
        return source_evidence.source_evidence_at(self.library_root, doc_id, page, bbox)

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
class SqliteAnchorRepository:
    """Repository for the ADR 0001 anchor index and page geometry."""

    library_root: Path

    def persist(
        self,
        doc_id: str,
        anchors: Sequence[LabelAnchor],
        geometry: Sequence[PageGeometry] = (),
    ) -> int:
        return label_anchor_store.persist_label_anchors(
            self.library_root, doc_id, anchors, geometry
        )

    def coverage(self, doc_id: str | None = None) -> dict[str, object]:
        return label_anchor_store.anchor_coverage(self.library_root, doc_id)


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

    def search_text(
        self, query: str, top_k: int, *, doc_id: str = ""
    ) -> list[dict[str, Any]]:
        return molecule_store.search_text(
            self.library_root, query, top_k, doc_id=doc_id
        )

    def search_substructure(
        self, query_smiles: str, top_k: int, *, doc_id: str = ""
    ) -> list[dict[str, Any]]:
        return molecule_store.search_substructure(
            self.library_root, query_smiles, top_k, doc_id=doc_id
        )

    def search_similarity(
        self, query_smiles: str, top_k: int, threshold: float, *, doc_id: str = ""
    ) -> list[dict[str, Any]]:
        return molecule_store.search_similarity(
            self.library_root, query_smiles, top_k, threshold, doc_id=doc_id
        )

    def detection_cache_matches(
        self, doc_id: str, page: int, query_box: tuple[float, float, float, float]
    ) -> list[dict[str, Any]]:
        return molecule_store.detection_cache_matches(
            self.library_root, doc_id, page, query_box
        )

    def identity_fields(self, mol_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        return molecule_store.identity_fields(self.library_root, mol_ids)

    def designated_structures(self, doc_id: str) -> list[dict[str, Any]]:
        return molecule_store.designated_structures(self.library_root, doc_id)

    def list_molecule_evidence(
        self, canonical_smiles: Sequence[str]
    ) -> list[dict[str, Any]]:
        return molecule_store.list_molecule_evidence(
            self.library_root, canonical_smiles
        )

    def evidence_for_molecules(
        self, mol_ids: Sequence[str], canonicals: Sequence[str]
    ) -> list[dict[str, Any]]:
        return molecule_store.evidence_for_molecules(
            self.library_root, mol_ids, canonicals
        )

    def load_detections(
        self, doc_id: str, page: int | None = None
    ) -> list[dict[str, Any]]:
        return detection_store.load_detections(self.library_root, doc_id, page)

    def save_detections(self, detections: Sequence[dict[str, Any]]) -> None:
        detection_store.save_detections(self.library_root, detections)

    def detection_counts(self) -> tuple[int, int]:
        return detection_store.detection_counts(self.library_root)

    def clear_detections(self, doc_id: str | None = None) -> int:
        return detection_store.clear_detections(self.library_root, doc_id)

    def molecules_for_recorrection(
        self, doc_id: str | None = None
    ) -> list[dict[str, Any]]:
        return molecule_store.molecules_for_recorrection(self.library_root, doc_id)

    def detections_for_molecules(self, mol_ids: Sequence[str]) -> list[dict[str, Any]]:
        return molecule_store.detections_for_molecules(self.library_root, mol_ids)

    def apply_corrections(self, updates: Sequence[dict[str, Any]]) -> None:
        molecule_store.apply_corrections(self.library_root, updates)

    def persist_candidates(self, doc_id: str, candidates: Sequence[Any]) -> int:
        return molecule_candidates.persist_candidates(
            self.library_root, doc_id, candidates
        )

    def replace_document_candidates(
        self,
        doc_id: str,
        candidates: Sequence[Any],
        activity_updates: Sequence[dict[str, Any]] | None = None,
    ) -> int:
        return molecule_candidates.replace_document_candidates(
            self.library_root, doc_id, candidates, activity_updates
        )


@dataclass
class SqliteReviewRepository:
    """Repository facade for review queue and audit persistence.

    Owns its connections: every method opens a unified-database transaction so
    callers never thread a ``conn``.
    """

    library_root: Path

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with DatabaseManager.get(str(self.library_root)).connection() as conn:
            yield conn

    def insert_review_item(self, **kwargs: Any) -> str:
        with self._conn() as conn:
            return insert_review_item(conn, **kwargs)

    def record_review_decision(self, **kwargs: Any) -> None:
        with self._conn() as conn:
            record_review_decision(conn, **kwargs)

    def list_queue(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        doc_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._conn() as conn:
            return review_store.list_queue(
                conn,
                kind=kind,
                status=status,
                doc_id=doc_id,
                page=page,
                page_size=page_size,
            )

    def get_item(self, kind: str, item_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            return review_store.get_item(conn, kind, item_id)

    def stats(self, doc_id: str | None = None) -> dict[str, Any]:
        with self._conn() as conn:
            return review_store.stats(conn, doc_id=doc_id)

    def history(self, entity_id: str) -> tuple[str, list[dict[str, Any]]]:
        with self._conn() as conn:
            return review_store.history(conn, entity_id)

    def review_item_status_payload(
        self, item_id: str, kind: str
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            return review_store.review_item_status_payload(conn, item_id, kind)

    def set_review_item_status(self, item_id: str, kind: str, new_status: str) -> None:
        with self._conn() as conn:
            review_store.set_review_item_status(conn, item_id, kind, new_status)

    def set_molecule_review_status(self, mol_id: str, status: str) -> None:
        with self._conn() as conn:
            review_store.set_molecule_review_status(conn, mol_id, status)

    def set_molecule_name(self, mol_id: str, name: str) -> None:
        with self._conn() as conn:
            review_store.set_molecule_name(conn, mol_id, name)

    def set_molecule_smiles(self, mol_id: str, smiles: str) -> None:
        molecule_store.update(
            self.library_root,
            mol_id,
            {"smiles": smiles},
            correction_source="smiles_correction_review",
        )

    def clear_all(self) -> dict[str, int]:
        with self._conn() as conn:
            return review_store.clear_all(conn)


@dataclass
class SqliteMeasurementRepository:
    """Readings and attributions; a reading needs no structure to be stored."""

    library_root: Path

    def list(self, query: MeasurementQuery) -> list[dict[str, Any]]:
        return measurement_store.list_measurements(self.library_root, query)

    def attributions_for(
        self, measurement_ids: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]:
        return measurement_store.list_attributions_for(
            self.library_root, measurement_ids
        )

    def measurements_for_molecules(
        self, mol_ids: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]:
        return measurement_store.measurements_for_molecules(
            self.library_root, mol_ids
        )

    def stats(self, doc_id: str = "") -> MeasurementDatasetStats:
        return measurement_store.dataset_stats(self.library_root, doc_id)

    def unattributed_readings(self, doc_id: str = "") -> list[dict[str, Any]]:
        return measurement_store.unattributed_readings(self.library_root, doc_id)

    def document_detection_count(self, doc_id: str) -> int:
        return molecule_store.document_detection_count(self.library_root, doc_id)

    def document_label_numbers(self, doc_id: str) -> set[str]:
        return molecule_store.document_label_numbers(self.library_root, doc_id)

    def unlabeled_structure_count(self, doc_id: str) -> int:
        return measurement_store.unlabeled_structure_count(self.library_root, doc_id)

    def bind_attribution(
        self,
        *,
        measurement_id: str,
        mol_id: str,
        doc_id: str,
        evidence_id: str = "",
        method: str = "human",
        confidence: float | None = None,
    ) -> str:
        return measurement_store.bind_attribution(
            self.library_root,
            measurement_id=measurement_id,
            mol_id=mol_id,
            doc_id=doc_id,
            evidence_id=evidence_id,
            method=method,
            confidence=confidence,
        )


@dataclass
class FilesystemArtifactStore:
    """Repository facade for the PDF page-count probe."""

    def read_pdf_page_count(self, document: Any) -> int:
        from mbforge.db.pdf_probe import read_pdf_page_count

        return read_pdf_page_count(document)


@dataclass
class SqliteDocumentRepository:
    """Repository for the ``documents`` registry table."""

    library_root: Path

    def insert(self, record: dict[str, Any]) -> None:
        document_records.insert(self.library_root, record)

    def get(self, doc_id: str) -> dict[str, Any] | None:
        return document_records.get(self.library_root, doc_id)

    def find_by_filename(self, file_name: str) -> dict[str, Any] | None:
        return document_records.find_by_filename(self.library_root, file_name)

    def list_rows(
        self, *, statuses: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        return document_records.list_rows(self.library_root, statuses=statuses)

    def count(self, *, statuses: Sequence[str] | None = None) -> int:
        return document_records.count(self.library_root, statuses=statuses)

    def update_status(self, doc_id: str, status: str) -> None:
        document_records.update_status(self.library_root, doc_id, status)

    def delete_many(self, doc_ids: Sequence[str]) -> None:
        document_records.delete_many(self.library_root, doc_ids)


@dataclass
class SqlitePatentAnalysisRepository:
    """Repository for the committed Patent-analysis state table."""

    library_root: Path

    def load(self, doc_id: str) -> dict[str, Any] | None:
        return patent_analysis_store.load_state(self.library_root, doc_id)

    def commit(self, **kwargs: Any) -> int:
        return patent_analysis_store.commit_document_facts(self.library_root, **kwargs)

    def clear_payload(self, doc_id: str) -> int:
        return patent_analysis_store.clear_payload(self.library_root, doc_id)

    def delete_document_state(self, doc_id: str) -> int:
        return patent_analysis_store.delete_document_state(self.library_root, doc_id)


@dataclass
class SqliteRepositories(LibraryRepositories):
    """Repositories for one library root."""

    library_root: Path
    _database: SqliteDatabaseRepository
    _review: SqliteReviewRepository
    _artifacts: FilesystemArtifactStore
    _patent_analysis: SqlitePatentAnalysisRepository

    @property
    def database(self) -> DatabaseRepository:
        return self._database

    @property
    def documents(self) -> SqliteDocumentRepository:
        return SqliteDocumentRepository(self.library_root)

    @property
    def evidence(self) -> SqliteEvidenceRepository:
        return SqliteEvidenceRepository(self.library_root)

    @property
    def anchors(self) -> SqliteAnchorRepository:
        return SqliteAnchorRepository(self.library_root)

    @property
    def molecules(self) -> SqliteMoleculeRepository:
        return SqliteMoleculeRepository(self.library_root)

    @property
    def measurements(self) -> SqliteMeasurementRepository:
        return SqliteMeasurementRepository(self.library_root)

    @property
    def review(self) -> SqliteReviewRepository:
        return self._review

    @property
    def patent_analysis(self) -> SqlitePatentAnalysisRepository:
        return self._patent_analysis

    @property
    def artifacts(self) -> FilesystemArtifactStore:
        return self._artifacts


def create_repositories(library_root: str | Path) -> SqliteRepositories:
    """Build the SQLite repository set for a library."""

    root = Path(library_root).expanduser().resolve()
    return SqliteRepositories(
        root,
        SqliteDatabaseRepository(DatabaseManager.get(str(root))),
        SqliteReviewRepository(root),
        FilesystemArtifactStore(),
        SqlitePatentAnalysisRepository(root),
    )


__all__ = [
    "SqliteDatabaseRepository",
    "SqliteDocumentRepository",
    "SqliteEvidenceRepository",
    "SqliteAnchorRepository",
    "SqliteMeasurementRepository",
    "SqliteRepositories",
    "SqliteMoleculeRepository",
    "SqlitePatentAnalysisRepository",
    "SqliteReviewRepository",
    "FilesystemArtifactStore",
    "create_repositories",
]

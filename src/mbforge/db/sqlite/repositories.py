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
    docking_store,
    document_backup,
    document_records,
    markush_enumeration_store,
    markush_sites_store,
    markush_transitions,
    molecule_store,
    review_store,
    source_evidence,
)
from mbforge.db.markush_candidates import persist_review_candidates
from mbforge.db.markush_transitions import _copy_evidence
from mbforge.db.review_audit import (
    insert_review_item,
    record_review_decision,
)
from mbforge.db.sqlite.database import (
    DatabaseManager,
    record_ingest_event,
)
from mbforge.domain.evidence import SourceEvidence
from mbforge.ports.repositories import (
    DatabaseRepository,
    LibraryRepositories,
)

#: Tables the ``library_stats`` agent tool reports a total for. The names double
#: as the reported keys, so the order here is the order the tool returns them.
_COUNTED_TABLES: tuple[str, ...] = (
    "documents",
    "source_evidence",
    "molecules",
    "activities",
    "markush_review_candidates",
    "review_items",
)


@dataclass
class SqliteDatabaseRepository:
    """Repository facade over one library's unified SQLite database."""

    _manager: DatabaseManager

    def initialize(self) -> None:
        self._manager.initialize()

    def readonly_schema(self) -> list[dict[str, Any]]:
        from mbforge.db.sqlite import readonly_sql

        return readonly_sql.introspect_schema(self._manager.kb_path)

    def readonly_query(self, sql: str, *, max_rows: int) -> dict[str, Any]:
        from mbforge.db.sqlite import readonly_sql

        return readonly_sql.run_query(self._manager.kb_path, sql, max_rows=max_rows)

    def table_counts(self) -> dict[str, int]:
        """Count the main library tables reported by the ``library_stats`` tool."""
        with self._manager.kb_conn() as conn:
            return {
                name: int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in _COUNTED_TABLES
            }

    def document_status_counts(self) -> dict[str, int]:
        """Count documents grouped by ``status``."""
        with self._manager.kb_conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM documents GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["c"]) for row in rows}

    def ping(self) -> None:
        """Open (and initialize) the unified database connection."""
        with self._manager.kb_conn():
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
        with self._manager.mol_conn() as conn:
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

    def persist_extraction(
        self,
        *,
        doc_id: str,
        evidence: Sequence[SourceEvidence] | object,
        candidates: Sequence[Any],
        recognition_version: int = 1,
    ) -> tuple[int, int]:
        """Persist evidence and review candidates atomically.

        Both writes run on one unified-database transaction so either both
        succeed or both roll back; returns ``(evidence_count, candidate_count)``.
        """
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            evidence_count = source_evidence.persist_source_evidence(
                self.library_root, evidence, conn=conn
            )
            candidate_count = persist_review_candidates(
                doc_id,
                candidates,
                conn=conn,
                recognition_version=recognition_version,
            )
        return evidence_count, candidate_count

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
    """Repository facade for Markush review, sites, and enumeration.

    Owns its connections: every method opens a unified-database transaction so
    callers never thread a ``conn``.
    """

    library_root: Path

    # --- Review candidates ---

    def list_candidates(self, **kwargs: Any) -> Any:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_transitions.list_candidates(conn, **kwargs)

    def get_candidate_detail(self, candidate_id: str) -> Any:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_transitions.get_candidate_detail(conn, candidate_id)

    def update_candidate(self, **kwargs: Any) -> Any:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_transitions.update_candidate(conn, **kwargs)

    # --- Attachment sites ---

    def scaffold_site_context(self, scaffold_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.scaffold_site_context(conn, scaffold_id)

    def insert_site(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_sites_store.insert_site(conn, **kwargs)

    def get_site_row(self, site_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.get_site_row(conn, site_id)

    def list_site_rows(self, scaffold_id: str) -> list[dict[str, Any]]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.list_site_rows(conn, scaffold_id)

    def update_site_row(self, **kwargs: Any) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.update_site_row(conn, **kwargs)

    # --- Options ---

    def site_status(self, site_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.site_status(conn, site_id)

    def fragment_status(self, fragment_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.fragment_status(conn, fragment_id)

    def fragment_smiles(self, fragment_id: str) -> str | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.fragment_smiles(conn, fragment_id)

    def insert_option(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_sites_store.insert_option(conn, **kwargs)

    def get_option_row(self, option_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.get_option_row(conn, option_id)

    def list_option_rows(self, site_id: str) -> list[dict[str, Any]]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.list_option_rows(conn, site_id)

    # --- Mounts ---

    def find_mount_row(self, site_id: str, fragment_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.find_mount_row(conn, site_id, fragment_id)

    def insert_mount(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_sites_store.insert_mount(conn, **kwargs)

    def get_mount_row(self, mount_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.get_mount_row(conn, mount_id)

    def apply_mount_decision(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_sites_store.apply_mount_decision(conn, **kwargs)

    def list_mount_rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_sites_store.list_mount_rows(conn, **kwargs)

    # --- Enumeration ---

    def resolve_authorized_selection(
        self, *, scaffold_id: str, selection: list[Any]
    ) -> Any:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_enumeration_store.resolve_authorized_selection(
                conn, scaffold_id=scaffold_id, selection=selection
            )

    def insert_generation_run_terminal(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_enumeration_store.insert_generation_run_terminal(conn, **kwargs)

    def record_enumeration_run(self, **kwargs: Any) -> int:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_enumeration_store.record_enumeration_run(conn, **kwargs)

    def get_generated_candidate(self, generated_id: str) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_enumeration_store.get_generated_candidate(conn, generated_id)

    def confirm_generated_candidate(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_enumeration_store.confirm_generated_candidate(conn, **kwargs)

    def reject_generated_candidate(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_enumeration_store.reject_generated_candidate(conn, **kwargs)

    def list_run_results(self, run_id: str) -> list[dict[str, Any]]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_enumeration_store.list_run_results(conn, run_id)


@dataclass
class SqliteReviewRepository:
    """Repository facade for review queue and audit persistence.

    Owns its connections: every method opens a unified-database transaction so
    callers never thread a ``conn``.
    """

    library_root: Path

    def insert_review_item(self, **kwargs: Any) -> str:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return insert_review_item(conn, **kwargs)

    def record_review_decision(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            record_review_decision(conn, **kwargs)

    def persist_review_candidates(
        self,
        doc_id: str,
        candidates: Any,
        recognition_version: int = 1,
    ) -> int:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return persist_review_candidates(
                doc_id,
                candidates,
                conn=conn,
                recognition_version=recognition_version,
            )

    def get_review_candidate(self, candidate_id: str) -> Any:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return markush_transitions.get_review_candidate(conn, candidate_id)

    def set_candidate_status(self, candidate_id: str, new_state: str) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_transitions.set_candidate_status(conn, candidate_id, new_state)

    def set_candidate_properties(self, candidate_id: str, properties_json: str) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_transitions.set_candidate_properties(
                conn, candidate_id, properties_json
            )

    def insert_molecule_from_candidate(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_transitions.insert_molecule_from_candidate(conn, **kwargs)

    def insert_scaffold_from_candidate(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_transitions.insert_scaffold_from_candidate(conn, **kwargs)

    def insert_fragment_from_candidate(self, **kwargs: Any) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            markush_transitions.insert_fragment_from_candidate(conn, **kwargs)

    def copy_evidence(
        self, row: Any, entity_type: str, entity_id: str, doc_id: str
    ) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            _copy_evidence(conn, row, entity_type, entity_id, doc_id)

    def list_queue(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        doc_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return review_store.list_queue(
                conn,
                kind=kind,
                status=status,
                doc_id=doc_id,
                page=page,
                page_size=page_size,
            )

    def get_item(self, kind: str, item_id: str) -> dict[str, Any]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return review_store.get_item(conn, kind, item_id)

    def stats(self) -> dict[str, Any]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return review_store.stats(conn)

    def history(self, entity_id: str) -> tuple[str, list[dict[str, Any]]]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return review_store.history(conn, entity_id)

    def markush_candidate_version(self, item_id: str) -> int | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return review_store.markush_candidate_version(conn, item_id)

    def review_item_status_payload(
        self, item_id: str, kind: str
    ) -> dict[str, Any] | None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return review_store.review_item_status_payload(conn, item_id, kind)

    def set_review_item_status(self, item_id: str, kind: str, new_status: str) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            review_store.set_review_item_status(conn, item_id, kind, new_status)

    def set_molecule_review_status(self, mol_id: str, status: str) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            review_store.set_molecule_review_status(conn, mol_id, status)

    def set_molecule_name(self, mol_id: str, name: str) -> None:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            review_store.set_molecule_name(conn, mol_id, name)

    def clear_all(self) -> dict[str, int]:
        with DatabaseManager.get(str(self.library_root)).mol_conn() as conn:
            return review_store.clear_all(conn)


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
class SqliteDockingRepository:
    """Repository for receptors, docking jobs and poses."""

    library_root: Path

    def insert_receptor(self, receptor: dict[str, Any]) -> None:
        docking_store.insert_receptor(self.library_root, receptor)

    def list_receptors(self) -> list[dict[str, Any]]:
        return docking_store.list_receptors(self.library_root)

    def get_receptor(self, receptor_id: str) -> dict[str, Any] | None:
        return docking_store.get_receptor(self.library_root, receptor_id)

    def delete_receptor(self, receptor_id: str) -> int:
        return docking_store.delete_receptor(self.library_root, receptor_id)

    def insert_job(self, job: dict[str, Any]) -> None:
        docking_store.insert_job(self.library_root, job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return docking_store.get_job(self.library_root, job_id)

    def list_jobs(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return docking_store.list_jobs(self.library_root, status=status, limit=limit)

    def claim_next_pending(self, worker: str) -> dict[str, Any] | None:
        return docking_store.claim_next_pending(self.library_root, worker)

    def set_job_status(
        self,
        job_id: str,
        status: str,
        *,
        progress: float | None = None,
        message: str | None = None,
        error: str | None = None,
        finished: bool = False,
    ) -> None:
        docking_store.set_job_status(
            self.library_root,
            job_id,
            status,
            progress=progress,
            message=message,
            error=error,
            finished=finished,
        )

    def reset_running_jobs(self) -> int:
        return docking_store.reset_running_jobs(self.library_root)

    def insert_pose(self, pose: dict[str, Any]) -> None:
        docking_store.insert_pose(self.library_root, pose)

    def list_poses(self, job_id: str) -> list[dict[str, Any]]:
        return docking_store.list_poses(self.library_root, job_id)

    def get_pose(self, pose_id: str) -> dict[str, Any] | None:
        return docking_store.get_pose(self.library_root, pose_id)


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
    def documents(self) -> SqliteDocumentRepository:
        return SqliteDocumentRepository(self.library_root)

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
    def docking(self) -> SqliteDockingRepository:
        return SqliteDockingRepository(self.library_root)

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
        SqliteDatabaseRepository(DatabaseManager.get(str(root))),
        SqliteMarkushRepository(root),
        SqliteReviewRepository(root),
        FilesystemArtifactStore(),
    )


__all__ = [
    "SqliteActivityRepository",
    "SqliteDatabaseRepository",
    "SqliteDocumentRepository",
    "SqliteEvidenceRepository",
    "SqliteRepositories",
    "SqliteMarkushRepository",
    "SqliteMoleculeRepository",
    "SqliteReviewRepository",
    "FilesystemArtifactStore",
    "create_repositories",
]

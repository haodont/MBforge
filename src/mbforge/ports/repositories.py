"""Repository ports for application use cases.

The application layer receives these contracts from the composition root.  A
use case may ask for a repository for a library, but it never constructs a
SQLite connection or imports a persistence adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from mbforge.contracts.measurement import (
    MeasurementDatasetStats,
    MeasurementQuery,
)
from mbforge.contracts.molecule import MoleculeListRequest
from mbforge.domain.evidence import SourceEvidence


@runtime_checkable
class DatabaseRepository(Protocol):
    """The library database boundary exposed to application code.

    The concrete adapter owns the connection implementation; this port exposes
    only the typed operations the application layer needs instead of leaking
    ``DatabaseManager`` or raw SQLite connections.
    """

    def initialize(self) -> None: ...

    def readonly_schema(self) -> list[dict[str, Any]]: ...

    def readonly_query(self, sql: str, *, max_rows: int) -> dict[str, Any]: ...

    def snapshot_document(self, doc_id: str) -> dict[str, Any]: ...

    def record_ingest_event(self, **kwargs: Any) -> None: ...

    def table_counts(self) -> dict[str, int]: ...

    def document_status_counts(self) -> dict[str, int]: ...

    def ping(self) -> None: ...

    def delete_document_molecule_data(self, doc_id: str) -> int: ...


class EvidenceRepository(Protocol):
    """Canonical SourceEvidence persistence and read contract."""

    def persist(self, evidence: Sequence[SourceEvidence] | object) -> int: ...

    def persist_extraction(
        self,
        *,
        doc_id: str,
        evidence: Sequence[SourceEvidence] | object,
        candidates: Sequence[Any],
        recognition_version: int = 1,
    ) -> tuple[int, int]:
        """Persist canonical evidence and review candidates in one transaction.

        Returns ``(evidence_count, candidate_count)``.
        """
        ...

    def get(self, evidence_id: str) -> SourceEvidence | None: ...

    def search(
        self, query: str, *, doc_id: str = "", limit: int = 20, offset: int = 0
    ) -> list[dict[str, object]]: ...

    def list(
        self,
        doc_id: str,
        *,
        page: int | None = None,
        kind: str | None = None,
        limit: int | None = None,
        offset: int = 0,
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

    def designated_structures(self, doc_id: str) -> list[dict[str, Any]]:
        """Concrete structures of one document, each with its printed designation.

        Returns ``{name, canonical_smiles}`` rows. A Markush scaffold is excluded:
        its ``name`` is a scheme label (``I-A``), never the number an activity
        table prints for a finished compound.
        """
        ...

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


class MeasurementRepository(Protocol):
    """Readings and their structure attributions.

    A reading exists independently of any structure: ``list`` returns rows
    whether or not they resolve to a molecule, and ``attributed_to`` answers
    "which structures does this document's data actually reach".
    """

    def list(self, query: MeasurementQuery) -> list[dict[str, Any]]: ...

    def attributions_for(
        self, measurement_ids: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]: ...

    def stats(self, doc_id: str = "") -> MeasurementDatasetStats: ...

    def unattributed_readings(self, doc_id: str = "") -> list[dict[str, Any]]: ...

    def document_detection_count(self, doc_id: str) -> int: ...

    def document_label_numbers(self, doc_id: str) -> set[str]: ...

    def unlabeled_structure_count(self, doc_id: str) -> int: ...

    def bind_attribution(
        self,
        *,
        measurement_id: str,
        mol_id: str,
        doc_id: str,
        evidence_id: str = "",
        method: str = "human",
    ) -> str: ...


class MarkushRepository(Protocol):
    """Markush review persistence contract.

    Every method owns its connection; callers never thread one in.
    """

    # --- Review candidates ---
    def list_candidates(self, **kwargs: Any) -> Any: ...

    def get_candidate_detail(self, candidate_id: str) -> Any: ...

    def update_candidate(self, **kwargs: Any) -> Any: ...


class ReviewRepository(Protocol):
    """Persistence boundary for native and Markush review records."""

    def insert_review_item(self, **kwargs: Any) -> str: ...

    def record_review_decision(self, **kwargs: Any) -> None: ...

    def persist_review_candidates(
        self,
        doc_id: str,
        candidates: Any,
        recognition_version: int = 1,
    ) -> int: ...

    def copy_evidence(
        self, row: Any, entity_type: str, entity_id: str, doc_id: str
    ) -> None: ...

    def get_review_candidate(self, candidate_id: str) -> Any: ...

    def set_candidate_status(self, candidate_id: str, new_state: str) -> None: ...

    def set_candidate_properties(
        self, candidate_id: str, properties_json: str
    ) -> None: ...

    def insert_molecule_from_candidate(self, **kwargs: Any) -> None: ...

    def insert_scaffold_from_candidate(self, **kwargs: Any) -> None: ...

    def insert_fragment_from_candidate(self, **kwargs: Any) -> None: ...

    def list_queue(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        doc_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def get_item(self, kind: str, item_id: str) -> dict[str, Any]: ...

    def stats(self) -> dict[str, Any]: ...

    def history(self, entity_id: str) -> tuple[str, list[dict[str, Any]]]: ...

    def markush_candidate_version(self, item_id: str) -> int | None: ...

    def review_item_status_payload(
        self, item_id: str, kind: str
    ) -> dict[str, Any] | None: ...

    def set_review_item_status(
        self, item_id: str, kind: str, new_status: str
    ) -> None: ...

    def set_molecule_review_status(self, mol_id: str, status: str) -> None: ...

    def set_molecule_name(self, mol_id: str, name: str) -> None: ...

    def set_molecule_smiles(self, mol_id: str, smiles: str) -> None: ...

    """Apply a reviewer-confirmed structure, keeping ``mol_id`` and its links."""

    def clear_all(self) -> dict[str, int]: ...


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


class PatentAnalysisRepository(Protocol):
    """Committed Patent-analysis state: one authoritative snapshot per document.

    ``patent_facts.json`` is a rebuildable projection of this row. A commit
    writes the snapshot, the human decisions and the permitted derived rows in a
    single transaction, so the facts and the derived molecules cannot disagree.
    """

    def load(self, doc_id: str) -> dict[str, Any] | None:
        """Return the committed state for *doc_id* (``None`` when absent)."""
        ...

    def commit(
        self,
        *,
        doc_id: str,
        evidence_signature: str,
        analysis_status: str,
        extraction_mode: str,
        payload: dict[str, Any],
        candidates: Sequence[Any] = (),
        activity_updates: Sequence[dict[str, Any]] | None = None,
        measurements: Sequence[Any] = (),
        attributions: Sequence[Any] = (),
        decisions: dict[str, Any] | None = None,
        forget_decisions: Sequence[str] = (),
        expected_revision: int | None = None,
    ) -> int:
        """Commit one revision; raises ``ConflictError`` when the caller is stale.

        ``decisions`` merges into the stored map and ``forget_decisions`` removes
        slots whose decision was withdrawn.
        """
        ...

    def clear_payload(self, doc_id: str) -> int:
        """Drop the committed facts but keep the human decisions."""
        ...

    def delete_document_state(self, doc_id: str) -> int:
        """Remove the document's state entirely (document deletion)."""
        ...


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
    def measurements(self) -> MeasurementRepository: ...

    @property
    def markush(self) -> MarkushRepository: ...

    @property
    def review(self) -> ReviewRepository: ...

    @property
    def patent_analysis(self) -> PatentAnalysisRepository: ...

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
    "MeasurementRepository",
    "MoleculeRepository",
    "PatentAnalysisRepository",
    "ReviewRepository",
    "RepositoryFactory",
    "configure_repository_factory",
    "get_database",
    "get_repositories",
]

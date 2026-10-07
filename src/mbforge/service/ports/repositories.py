"""Back-compat re-export of the repository ports.

The contracts moved to :mod:`mbforge.ports.repositories` (neutral layer) so
``db`` can implement them without importing ``service``. Existing
``service``/test importers keep working through this shim.
"""

from mbforge.ports.repositories import (
    ActivityRepository,
    ArtifactStore,
    DatabaseRepository,
    DockingRepository,
    DocumentRepository,
    EvidenceRepository,
    LibraryRepositories,
    MarkushRepository,
    MoleculeRepository,
    RepositoryFactory,
    ReviewRepository,
    configure_repository_factory,
    get_database,
    get_repositories,
)

__all__ = [
    "ActivityRepository",
    "ArtifactStore",
    "DatabaseRepository",
    "DocumentRepository",
    "DockingRepository",
    "EvidenceRepository",
    "LibraryRepositories",
    "MarkushRepository",
    "MoleculeRepository",
    "RepositoryFactory",
    "ReviewRepository",
    "configure_repository_factory",
    "get_database",
    "get_repositories",
]

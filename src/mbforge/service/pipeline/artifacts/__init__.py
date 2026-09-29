"""Public façade for the page-evidence boundary."""

from mbforge.service.pipeline.artifacts.evidence_join import (
    evidence_ids_for,
    load_document_evidence,
    mint_evidence,
    observation_from_payload,
    observation_payload,
    page_frames_from_pdf,
    summarize_molecules,
)
from mbforge.service.pipeline.artifacts.evidence_models import PageFrame
from mbforge.service.pipeline.artifacts.hydration import (
    hydrate_context_from_evidence,
    load_detections,
    load_extracted,
    register_evidence_kinds,
)
from mbforge.service.pipeline.artifacts.staging import (
    cleanup_staging,
    promote_staging,
    publish_run,
    staging_dir,
)

__all__ = [
    "PageFrame",
    "cleanup_staging",
    "evidence_ids_for",
    "hydrate_context_from_evidence",
    "load_detections",
    "load_document_evidence",
    "load_extracted",
    "mint_evidence",
    "observation_from_payload",
    "observation_payload",
    "page_frames_from_pdf",
    "promote_staging",
    "publish_run",
    "register_evidence_kinds",
    "staging_dir",
    "summarize_molecules",
]

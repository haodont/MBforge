"""Public façade for the run-scoped artifact boundary."""

from .branch_io import (
    branch_path,
    build_detection_artifact,
    build_extract_artifact,
    detection_results,
    load_detection_branch,
    load_extract_branch,
    page_frames_from_pdf,
    save_detection_branch,
    save_extract_branch,
)
from .evidence_join import (
    evidence_ids_for,
    join_evidence_artifacts,
    load_document_evidence,
    summarize_molecules,
)
from .evidence_models import (
    CandidateArtifact,
    DetectionArtifact,
    DetectionPage,
    DocumentEvidenceArtifact,
    ExtractArtifact,
    ExtractPage,
    PageFrame,
)
from .hydration import hydrate_context_from_artifacts, load_detections, load_extracted
from .staging import (
    cleanup_staging,
    promote_staging,
    publish_run,
    reap_stage_run,
    staging_dir,
)

__all__ = [
    "CandidateArtifact",
    "DetectionArtifact",
    "DetectionPage",
    "DocumentEvidenceArtifact",
    "ExtractArtifact",
    "ExtractPage",
    "PageFrame",
    "build_detection_artifact",
    "build_extract_artifact",
    "branch_path",
    "cleanup_staging",
    "detection_results",
    "evidence_ids_for",
    "hydrate_context_from_artifacts",
    "join_evidence_artifacts",
    "load_detection_branch",
    "load_detections",
    "load_document_evidence",
    "load_extract_branch",
    "load_extracted",
    "page_frames_from_pdf",
    "promote_staging",
    "publish_run",
    "reap_stage_run",
    "save_detection_branch",
    "save_extract_branch",
    "staging_dir",
    "summarize_molecules",
]

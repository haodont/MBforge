"""Run-scoped artifact staging for the pipeline (PIPE-13).

``storage/{doc_id}/images/`` and ``storage/{doc_id}/crops/`` are evidence for
successful runs and must never be deleted unconditionally. Each pipeline run
writes new evidence into ``storage/{doc_id}/.staging/`` and the
runner promotes it into the canonical ``images/`` / ``crops/`` directories
only after every stage succeeds. On failure or cancellation exactly this
run's staging directory is removed — evidence from previous successful runs
(including re-ingested documents) stays untouched. Successful promotion keeps
the small branch artifacts and checkpoint in staging so an explicit retry can
reuse the other initial branch without rerunning it.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from mbforge.application.pipeline.artifacts.branch_io import (
    branch_path as resolve_branch_path,
)
from mbforge.application.pipeline.artifacts.json_io import read_json_object
from mbforge.application.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.application.pipeline.run.ids import stage_kind_file
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.artifacts.staging")

# Structured reason code for cleanup/promotion failures (repair plan §11).
ARTIFACT_CLEANUP_FAILED = "ARTIFACT_CLEANUP_FAILED"

# Staging subdirectories that map to evidence dirs under ``storage/{doc_id}/``.
STAGED_EVIDENCE_DIRS = ("crops",)


def staging_dir(library_root: str | Path, doc_id: str) -> Path:
    """Return ``storage/{doc_id}/.staging/`` for this document."""
    return LibraryLayout(library_root).storage_dir(doc_id) / ".staging"


def _verified_staging_dir(
    staging: Path, library_root: str | Path, doc_id: str
) -> Path | None:
    """Return ``staging`` resolved, only when it is exactly the expected path.

    Cleanup must never recursively delete a directory whose identity was not
    verified against the resolver-owned staging location.
    """
    expected = staging_dir(library_root, doc_id).resolve()
    resolved = staging.resolve()
    if resolved != expected:
        logger.error(
            "Refusing to touch unverified staging dir: reason=%s path=%s expected=%s",
            ARTIFACT_CLEANUP_FAILED,
            resolved,
            expected,
        )
        return None
    return resolved


def promote_staging(
    staging: Path | None,
    library_root: str | Path,
    doc_id: str,
) -> None:
    """Move staged evidence files into ``storage/{doc_id}/images|crops``.

    Called only after every pipeline stage succeeded. Existing files from a
    previous successful run are replaced one file at a time; a failure is
    logged with the exact path and exception and re-raised so the run is
    marked failed instead of silently keeping half-promoted evidence. The
    branch JSON and checkpoint remain for stage-specific retries.
    """
    if staging is None:
        return
    verified = _verified_staging_dir(staging, library_root, doc_id)
    if verified is None or not verified.exists():
        return
    resolver = LibraryLayout(library_root)
    targets = {
        "crops": resolver.crops_dir(doc_id),
    }
    for name in STAGED_EVIDENCE_DIRS:
        src_dir = verified / name
        if not src_dir.is_dir():
            continue
        dst_dir = targets[name]
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(src_dir.rglob("*")):
            if not src.is_file():
                continue
            dst = dst_dir / src.relative_to(src_dir)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            except Exception as exc:
                logger.error(
                    "Failed to promote staged artifact: reason=%s path=%s error=%s",
                    ARTIFACT_CLEANUP_FAILED,
                    src,
                    exc,
                )
                raise


def cleanup_staging(
    staging: Path | None,
    library_root: str | Path,
    doc_id: str,
) -> None:
    """Delete exactly this document's staging directory — nothing else.

    Only invoked on failure or cancellation. The directory identity is
    verified before any recursive delete; cleanup failures are logged with the
    exact path and exception and never raised, so a cleanup problem cannot mask
    the original pipeline error.
    """
    if staging is None:
        return
    verified = _verified_staging_dir(staging, library_root, doc_id)
    if verified is None or not verified.exists():
        return
    try:
        shutil.rmtree(verified)
    except Exception as exc:
        logger.error(
            "Failed to clean staged artifacts: reason=%s path=%s error=%s",
            ARTIFACT_CLEANUP_FAILED,
            verified,
            exc,
        )
        return
    # Remove the now-empty ``.staging`` parent when this was the last run.
    with contextlib.suppress(OSError):
        verified.parent.rmdir()


# --- run publication (file-first, spec §3) -----------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON via temp file + ``os.replace`` (crash-atomic per file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def publish_run(
    library_root: str | Path,
    doc_id: str,
    run_id: str,
    *,
    patent_facts: PatentFactsArtifact | None = None,
    stage: str | None = None,
) -> Path:
    """Publish the current Patent facts artifact at the document root."""
    if patent_facts is None or (stage is not None and stage != "patent"):
        raise ValueError("publish_run requires patent_facts for the patent stage")
    artifact_path = (
        LibraryLayout(library_root).storage_dir(doc_id) / "patent_facts.json"
    )
    _atomic_write_json(artifact_path, patent_facts.model_dump())
    logger.info(
        "Published patent facts for %s (run %s): %s", doc_id, run_id, artifact_path
    )
    return artifact_path


def reap_stage_run(
    library_root: str | Path, doc_id: str, stage: str, run_id: str
) -> None:
    """Remove one superseded Extract/Detection branch artifact.

    A staged branch is removed only when its embedded run ID matches the
    superseded run.
    """
    if stage not in ("extract", "detection"):
        return
    kind = stage_kind_file(stage)
    if kind is None:
        return
    branch_path = resolve_branch_path(library_root, doc_id, kind)
    data = read_json_object(branch_path)
    if data is not None and data.get("run_id") == run_id:
        branch_path.unlink()

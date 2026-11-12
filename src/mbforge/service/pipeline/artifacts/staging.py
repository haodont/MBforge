"""Run-scoped artifact staging for the pipeline (PIPE-13).

``storage/{doc_id}/crops/`` is evidence for successful runs and must never be
deleted unconditionally. Each pipeline run writes new crops into
``storage/{doc_id}/.staging/`` and the runner promotes them into the canonical
``crops/`` directory only after every stage succeeds. On failure or
cancellation exactly this run's staging directory is removed — evidence from
previous successful runs (including re-ingested documents) stays untouched.
Successful promotion keeps the checkpoint in staging so an explicit retry can
reuse completed work without rerunning it.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.service.pipeline.artifacts.staging")

# Structured reason code for cleanup/promotion failures.
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
    checkpoint remains for stage-specific retries.
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

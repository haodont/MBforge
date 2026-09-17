"""Regression tests for run-scoped artifact staging (PIPE-13).

Each pipeline run stages new images/crops evidence under
``storage/{doc_id}/.staging/``. Success promotes it into the
canonical evidence dirs; failure or cancellation removes exactly this run's
staging directory and never touches evidence from previous successful runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mbforge.pipeline.artifacts.staging import (
    cleanup_staging,
    staging_dir,
)
from mbforge.pipeline.cancellation import TaskCancelledError
from mbforge.pipeline.extract.text import ExtractedDocument, PageContent
from mbforge.pipeline.runner import cancel_task, run_pipeline
from mbforge.storage.layout import LibraryLayout

_DOC_ID = "sample_doc"
_RUN_ID = "20260909123456"


def _dag_order() -> list[str]:
    """Topological order of the stage DAG (matches the queue's node order)."""
    from mbforge.pipeline.composition import stage_dependencies

    deps = stage_dependencies()
    order: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(s for s, d in remaining.items() if all(x in order for x in d))
        for stage in ready:
            order.append(stage)
            remaining.pop(stage)
    return order


def _fake_extract_pdf_text(
    pdf_path: str,
    ocr_fallback: bool = True,
    ocr_config: dict | None = None,
    cancel_check: Any = None,
) -> ExtractedDocument:
    """Stand-in for extract_pdf_text."""
    return ExtractedDocument(
        raw_text="page one text\n\npage two text",
        page_count=2,
        pages=[
            PageContent(page_num=1, text="page one text"),
            PageContent(page_num=2, text="page two text"),
        ],
    )


def _fake_extract_molecules(
    pdf_path: str,
    library_root: str,
    doc_id: str,
    max_pages: int | None = None,
    cancel_check: Any = None,
    staging_dir: Any = None,
    ocr_config: Any = None,
    ocr_spans_by_page: Any = None,
) -> list:
    """Stand-in for extract_molecules_from_pdf that drops one staged crop."""
    if staging_dir:
        target = Path(staging_dir) / "crops"
        target.mkdir(parents=True, exist_ok=True)
        (target / "crop1.png").write_bytes(b"new-crop")
    return []


def _run(
    sample_pdf: Path,
    library_root: Path,
    *,
    task_id: str | None = None,
    fail_patent_publish: bool = False,
    on_progress: Any = None,
):
    patches = [
        patch(
            "mbforge.pipeline.extract.text.extract_pdf_text",
            side_effect=_fake_extract_pdf_text,
        ),
        patch(
            "mbforge.pipeline.detection.extraction.extract_molecules_from_pdf",
            side_effect=_fake_extract_molecules,
        ),
    ]
    if fail_patent_publish:
        patches.append(
            patch(
                "mbforge.pipeline.artifacts.staging.publish_run",
                side_effect=RuntimeError("disk full"),
            )
        )
    import contextlib

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        last_result = None
        for stage in _dag_order():
            last_result = run_pipeline(
                str(sample_pdf),
                str(library_root),
                doc_id=_DOC_ID,
                stage=stage,
                run_id=_RUN_ID,
                task_id=task_id,
                on_progress=on_progress,
            )

        # Simulate the worker's finalization: write merged report + promote.
        from mbforge.pipeline.artifacts.staging import promote_staging
        from mbforge.pipeline.artifacts.staging import staging_dir as _sd
        from mbforge.pipeline.run.checkpoint import write_merged_report

        staging = _sd(str(library_root), _DOC_ID)
        write_merged_report(staging, doc_id=_DOC_ID, library_root=str(library_root))
        promote_staging(staging, str(library_root), _DOC_ID)

        return last_result


@pytest.fixture()
def library_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_cancel_cleans_staging(sample_pdf: Path, library_root: Path) -> None:
    resolver = LibraryLayout(library_root)

    # Cancel the task before starting; the runner detects it at the
    # first stage boundary and raises TaskCancelledError.
    cancel_task("cancel-staging")

    with pytest.raises(TaskCancelledError):
        _run(
            sample_pdf,
            library_root,
            task_id="cancel-staging",
        )

    # Promoted evidence was never written (pipeline was cancelled).
    assert not (resolver.crops_dir(_DOC_ID) / "crop1.png").exists()


def test_failed_reingest_keeps_old_evidence(
    sample_pdf: Path, library_root: Path
) -> None:
    """A failed re-ingest must not overwrite or remove the previous run's evidence."""
    resolver = LibraryLayout(library_root)
    old_crop = resolver.crops_dir(_DOC_ID) / "crop1.png"
    old_crop.parent.mkdir(parents=True, exist_ok=True)
    old_crop.write_bytes(b"old-crop")

    with pytest.raises(RuntimeError, match="disk full"):
        _run(sample_pdf, library_root, fail_patent_publish=True)

    # The old evidence is untouched because promotion never happened.
    assert old_crop.read_bytes() == b"old-crop"


def test_cleanup_refuses_unverified_directory(
    tmp_path: Path, library_root: Path
) -> None:
    """cleanup_staging must never recursively delete a non-staging directory."""
    resolver = LibraryLayout(library_root)
    storage = resolver.storage_dir(_DOC_ID)
    storage.mkdir(parents=True, exist_ok=True)
    sentinel = storage / "report.json"
    sentinel.write_text("{}", encoding="utf-8")

    # Passing the whole document storage dir as "staging" must be refused.
    cleanup_staging(storage, library_root, _DOC_ID)
    assert sentinel.exists()

    # The real staging dir for the run is removed.
    real_staging = staging_dir(library_root, _DOC_ID)
    (real_staging / "crops").mkdir(parents=True)
    (real_staging / "crops" / "x.png").write_bytes(b"x")
    cleanup_staging(real_staging, library_root, _DOC_ID)
    assert not real_staging.exists()
    assert sentinel.exists()

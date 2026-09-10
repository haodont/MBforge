"""Shared pytest fixtures for MBForge."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def scratch() -> Iterator[Path]:
    """Return a unique workspace-local scratch directory.

    pytest's built-in ``tmp_path`` machinery creates directories with
    restricted ACLs that some sandboxed environments cannot list or remove,
    and ``tempfile.mkdtemp`` directories are likewise unwritable there. A
    plain ``mkdir`` directory under ``<repo>/.tmp`` avoids both issues.
    """
    import uuid

    tmp_root = Path.cwd() / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    base = tmp_root / f"mbforge-scratch-{uuid.uuid4().hex}"
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def tmp_path(scratch: Path) -> Path:
    """Redirect pytest's ``tmp_path`` to a plain workspace-local directory.

    Some sandboxed environments cannot list/remove pytest's restricted-ACL
    temp dirs; routing every ``tmp_path`` through :func:`scratch` keeps the
    usual per-test semantics (unique, empty, pre-created) without touching
    the system temp area.
    """
    sub = scratch / "tmp"
    sub.mkdir(parents=True, exist_ok=True)
    return sub


@pytest.fixture
def tmp_library(scratch: Path) -> Path:
    """Return a temporary library root pre-created on disk.

    Backed by :func:`scratch` (a plain workspace-local directory) instead
    of pytest's ``tmp_path`` so router tests also run in environments where
    pytest's restricted-ACL temp directories cannot be read or removed.
    """
    lib = scratch / "library"
    lib.mkdir(parents=True, exist_ok=True)
    return lib


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a minimal 2-page text PDF for pipeline integration tests."""
    pdf_path = tmp_path / "sample.pdf"
    # Import inside fixture so tests that do not need PDFs avoid the import.
    import fitz

    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_text(
            (72, 72),
            f"Page {i + 1}. This document contains enough native text to avoid OCR fallback.",
            fontsize=12,
        )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def app_client(tmp_library: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient with global config pointing to a temp library."""
    from mbforge.app import app
    from mbforge.infra.ingest import worker
    from mbforge.utils import config

    # Routers must never start a real worker during router tests: enqueueing
    # still persists rows; the durable worker is exercised by dedicated unit
    # tests (tests/unit/core/test_queue_worker.py).
    monkeypatch.setattr(worker, "ensure_queue_worker", lambda _root: True)

    original_load = config.load_global_config

    class _PatchedLoad:
        def __call__(self):
            cfg = original_load()
            cfg.library_root = str(tmp_library)
            return cfg

        def cache_clear(self):
            original_load.cache_clear()

    patched = _PatchedLoad()

    # Routers that imported ``load_global_config`` directly must be patched
    # in their own module namespace; patching ``config.load_global_config``
    # only affects runtime lookups inside ``mbforge.utils.config``.
    monkeypatch.setattr(config, "load_global_config", patched)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _disable_llm_completion_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep LLM completion cache out of tests.

    ``_llm_complete`` caches successful responses on disk; tests that mock
    ``litellm.completion`` must never read or write that shared cache
    (a cached entry would short-circuit the mock and break call-count and
    credential assertions). Individual cache tests re-enable it with an
    isolated ``MBFORGE_LLM_CACHE_DIR``.
    """
    monkeypatch.setenv("MBFORGE_LLM_CACHE", "0")


@pytest.fixture(autouse=True)
def _clear_singleton_caches() -> None:
    """Clear module-level singleton caches after every test for isolation."""
    yield
    from mbforge.services.documents.library import LibraryStore
    from mbforge.storage.sqlite.database import DatabaseManager

    DatabaseManager.get.cache_clear()
    LibraryStore.get.cache_clear()

"""Shared pytest fixtures for MBForge."""

from __future__ import annotations

import contextlib
import importlib
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mbforge.db.sqlite.repositories import create_repositories
from mbforge.foundation import config as app_config
from mbforge.foundation.config import AppConfig
from mbforge.server.runtime_provider import create_runtime_provider
from mbforge.service.pipeline.runtime import create_pipeline_runtime
from mbforge.service.ports import (
    configure_pipeline_runtime,
    configure_repository_factory,
    configure_runtime_provider,
)

# Keep the suite independent from a developer's personal settings.json. In
# particular, a local Hiro layout setting would load ONNX weights during tests.
_TEST_APP_DIR = Path.cwd() / ".tmp" / "pytest-app"
_TEST_APP_DIR.mkdir(parents=True, exist_ok=True)
app_config.GLOBAL_APP_DIR = _TEST_APP_DIR
app_config._SETTINGS_PATH = _TEST_APP_DIR / "settings.json"
app_config._SETTINGS_PATH.unlink(missing_ok=True)
app_config.load_global_config.cache_clear()

# Redirect every ``tempfile`` consumer into the workspace-local scratch dir.
# ``tempfile.mkdtemp`` directories are unwritable in the sandboxed environments
# this suite runs in, so ``tempfile.gettempdir()`` falls back to the current
# working directory — which drops stray ``tmp*.md`` scratch files and the
# readiness demo PDF into the repository root. Pinning the module-level
# override keeps all of it inside the gitignored ``.tmp/``.
_TMP_ROOT = Path.cwd() / ".tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_TMP_ROOT)

# Direct application-use-case tests do not import the FastAPI composition
# root.  Configure the same concrete adapter once for the test composition
# root so those tests exercise the repository boundary as production does.
configure_repository_factory(create_repositories)
configure_runtime_provider(create_runtime_provider())
configure_pipeline_runtime(create_pipeline_runtime())


def _install_config_patch(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[AppConfig], None],
) -> None:
    """Point ``load_global_config`` at a mutated, isolated copy.

    ``load_global_config`` is ``lru_cache``d and hands out a *mutable*
    ``AppConfig``. A test that edits that shared instance in place (setting
    ``library_root``, flipping ``ingest.auto_enqueue_on_import`` …) would leak
    into every later test. The replacement accessor therefore deep-copies the
    real config before mutating it, so edits stay local. It also forwards
    ``cache_clear`` to the real accessor for callers that pre-clear the cache.
    """
    original = app_config.load_global_config

    class _PatchedLoad:
        def __call__(self) -> AppConfig:
            cfg = original().model_copy(deep=True)
            mutate(cfg)
            return cfg

        def cache_clear(self) -> None:
            original.cache_clear()

    monkeypatch.setattr(app_config, "load_global_config", _PatchedLoad())


@pytest.fixture
def patch_config(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[AppConfig], None]], None]:
    """Return a helper that points ``load_global_config`` at a mutated copy."""

    def _patch(mutate: Callable[[AppConfig], None]) -> None:
        _install_config_patch(monkeypatch, mutate)

    return _patch


@pytest.fixture
def patch_config_root(
    patch_config: Callable[[Callable[[AppConfig], None]], None],
) -> Callable[[str | Path], None]:
    """Return a helper that pins ``load_global_config``'s ``library_root``."""

    def _patch(root: str | Path) -> None:
        patch_config(lambda cfg: setattr(cfg, "library_root", str(root)))

    return _patch


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
    import pymupdf

    doc = pymupdf.open()
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
def app_client(
    tmp_library: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_config_root: Callable[[str | Path], None],
) -> TestClient:
    """FastAPI TestClient with global config pointing to a temp library."""
    from mbforge.server.app import app
    from mbforge.server.ingest import worker

    # Routers must never start a real worker during router tests: enqueueing
    # still persists rows; the durable worker is exercised by dedicated unit
    # tests (tests/unit/core/test_queue_worker.py).
    monkeypatch.setattr(worker, "ensure_queue_worker", lambda _root: True)

    # Routers that imported ``load_global_config`` directly must be patched
    # in their own module namespace; patching ``config.load_global_config``
    # only affects runtime lookups inside ``mbforge.foundation.config``.
    patch_config_root(tmp_library)
    return TestClient(app)


#: ``(module, reset callable)`` pairs for every process-wide model singleton.
#: A test that loads a model (or leaves one half-loaded after a mocked failure)
#: must not let it leak into the next test; each ``unload``/``_clear_engines``
#: drops the cached instance. Modules without a reset path are omitted.
_MODEL_SINGLETON_RESETS: tuple[tuple[str, str], ...] = (
    ("mbforge.foundation.inference.moldet_v2_ft", "unload"),
    ("mbforge.foundation.inference.hiro_layout", "unload"),
    ("mbforge.foundation.inference.molparser", "unload"),
    ("mbforge.foundation.inference.table_slanet", "unload"),
    ("mbforge.foundation.inference.ocr.label_reader", "unload"),
    ("mbforge.foundation.inference.ocr.crop_labels", "_clear_engines"),
    ("mbforge.foundation.inference.ocr.page_text", "_clear_engines"),
    ("mbforge.foundation.inference.ocr.daemon_client", "unload_daemon"),
)


def _reset_model_singletons() -> None:
    """Drop every process-wide model/OCR singleton that exposes a reset path."""
    for module_name, reset_name in _MODEL_SINGLETON_RESETS:
        try:
            module = importlib.import_module(module_name)
            reset = getattr(module, reset_name)
        except (ImportError, AttributeError):  # pragma: no cover — defensive
            continue
        with contextlib.suppress(Exception):  # best-effort isolation only
            reset()


@pytest.fixture(autouse=True)
def _clear_singleton_caches() -> None:
    """Reset process-wide caches/singletons after every test for isolation."""
    yield
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.foundation.config import load_global_config
    from mbforge.foundation.docking import get_docking_engine
    from mbforge.service.use_cases.documents.library import LibraryStore

    DatabaseManager.get.cache_clear()
    LibraryStore.get.cache_clear()
    # ``load_global_config`` returns a mutable object; clearing its cache
    # after every test guarantees a copy mutated in place cannot survive.
    load_global_config.cache_clear()
    get_docking_engine.cache_clear()
    _reset_model_singletons()

"""Smoke tests for all registered FastAPI routers.

Goal: ensure every router can be imported and responds to at least one endpoint
without raising an unhandled 500. We do not assert deep business logic here.
"""

from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import suppress

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a TestClient for the FastAPI app.

    Models are loaded lazily; no startup pre-warming to patch.
    """
    # Patch heavy startup routine before importing the app.
    import mbforge.infra.environment as _environment

    _orig_check_environment = getattr(_environment, "check_environment", lambda: None)

    def _noop() -> None:
        return None

    _environment.check_environment = _noop

    from mbforge.infra.ingest import worker

    _orig_ensure = worker.ensure_queue_worker
    worker.ensure_queue_worker = lambda _root: True  # type: ignore[assignment]

    c = None
    try:
        from mbforge.app import create_app

        app = create_app()
        c = TestClient(app)
        yield c
    finally:
        if c is not None:
            with suppress(CancelledError, RuntimeError):
                c.close()
        _environment.check_environment = _orig_check_environment
        worker.ensure_queue_worker = _orig_ensure


# One representative endpoint per router registered in app.py.
# Format: (method, path, request_body_or_query, expected_status_in)
ROUTES: list[tuple[str, str, dict | None, tuple[int, ...]]] = [
    # health (mounted at /api/v1)
    ("GET", "/api/v1/health", None, (200,)),
    # library
    ("GET", "/api/v1/library/status", None, (200,)),
    # documents
    ("POST", "/api/v1/documents/list", {}, (200,)),
    # pipeline
    ("GET", "/api/v1/pipeline/worker/status", None, (200,)),
    # molecule
    ("POST", "/api/v1/molecule/list", {}, (200, 422)),
    # chem
    ("POST", "/api/v1/chem/validate-smiles", {}, (200, 422)),
    # detection-cache
    ("POST", "/api/v1/detection-cache/stats", {}, (200, 422)),
    # notes
    ("POST", "/api/v1/notes/list", {}, (200, 422)),
    # settings
    ("GET", "/api/v1/settings", None, (200,)),
    # resource
    ("POST", "/api/v1/resource/cache-dir-info", {}, (200, 422)),
    # pdf document overlay
    ("POST", "/api/v1/pdf/document-overlay", {}, (200, 422)),
    # sar
    ("POST", "/api/v1/sar/build-matrix", {}, (200,)),
    # ocr
    ("GET", "/api/v1/ocr/chain-status", None, (200,)),
    # diagnostics
    ("GET", "/api/v1/diagnostics/stats", None, (200,)),
    # repository documentation pages
    ("GET", "/api/v1/docs/pages", None, (200, 400)),
    # moldet
    ("POST", "/api/v1/moldet/extract-pdf-page", {}, (422,)),
    # models (main-app include, not mounted model_server)
    ("POST", "/api/v1/models/mol/render", {"smiles": "CCO"}, (200, 422)),
    # molparser predict is POST "" under /api/v1/molparser — empty body is 422
    ("POST", "/api/v1/molparser", {}, (200, 422, 400)),
    # pdf_render
    ("POST", "/api/v1/pdf/render-pages", {}, (400, 422)),
]


@pytest.mark.parametrize("method, path, payload, expected_status", ROUTES)
def test_router_endpoint_responds(
    client: TestClient,
    method: str,
    path: str,
    payload: dict | None,
    expected_status: tuple[int, ...],
) -> None:
    """Each registered router should serve its representative endpoint without 500."""
    if method == "GET":
        response = client.get(path)
    elif method == "POST":
        response = client.post(path, json=payload or {})
    else:
        pytest.fail(f"Unsupported method: {method}")

    assert response.status_code in expected_status, (
        f"{method} {path} returned {response.status_code}: {response.text}"
    )


def test_no_double_prefix_model_routes(client: TestClient) -> None:
    """Model routes must not appear under /api/v1/models/api/v1/..."""
    # FastAPI 0.141+ keeps included routers as top-level ``_IncludedRouter``
    # entries, so their concrete paths are exposed through the OpenAPI schema
    # rather than directly on ``client.app.routes``.
    paths = set(client.app.openapi()["paths"])
    bad = {p for p in paths if "/api/v1/models/api/v1" in p}
    assert not bad, f"double-prefix routes still registered: {bad}"
    assert "/api/v1/models/mol/render" in paths
    assert "/api/v1/molparser" in paths or any(
        p.startswith("/api/v1/molparser") for p in paths
    )
    assert "/api/v1/pdf/render-pages" in paths
    # The SSE stream endpoint is registered; we avoid opening the infinite stream.
    assert "/api/v1/events/stream" in paths

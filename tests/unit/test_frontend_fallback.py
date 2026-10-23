"""Frontend static-serving fallback contract.

Covers ``create_app(serve_frontend=True)``: client-side routes fall back to the
React entry point, while a missing static asset with an extension stays a real
404 instead of being masked by the SPA fallback.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.server.app import create_app


def test_client_route_falls_back_to_entrypoint_but_missing_assets_stay_404(
    tmp_path: Path,
) -> None:
    """Client-side routes serve index.html; unknown assets remain 404."""
    # Create a minimal frontend dist with index.html
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<!DOCTYPE html><html><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    os.environ["FRONTEND_DIST"] = str(dist)
    try:
        client = TestClient(create_app(serve_frontend=True))
        response = client.get("/workspace")
        assert response.status_code == 200
        assert '<div id="root"></div>' in response.text

        # Static asset paths with a suffix must not be swallowed by the SPA
        # fallback.
        missing = client.get("/assets/does-not-exist.js")
        assert missing.status_code == 404
    finally:
        os.environ.pop("FRONTEND_DIST", None)

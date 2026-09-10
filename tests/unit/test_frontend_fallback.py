import os
from pathlib import Path

from fastapi.testclient import TestClient

from mbforge.app import create_app


def test_client_side_route_serves_react_entrypoint(tmp_path: Path) -> None:
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
    finally:
        os.environ.pop("FRONTEND_DIST", None)


def test_missing_frontend_asset_remains_not_found() -> None:
    client = TestClient(create_app(serve_frontend=True))

    response = client.get("/assets/does-not-exist.js")

    assert response.status_code == 404

"""Contract: get_api_surface exposes live route and request-model metadata."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_api_surface_reports_render_contract_and_paginates(
    app_client: TestClient,
) -> None:
    response = app_client.post(
        "/api/v1/capabilities/get_api_surface",
        json={"path_contains": "/api/v1/pdf/render-pages"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total"] == 1

    route = data["routes"][0]
    assert route["path"] == "/api/v1/pdf/render-pages"
    assert route["methods"] == ["POST"]
    assert route["request_model"] == "RenderPagesRequest"
    fields = {field["name"]: field for field in route["fields"]}
    assert fields["pdf_path"]["required"] is False
    assert fields["page_indices"]["type"] == "list[int] | None"
    assert fields["dpi"]["default"] == 200
    assert fields["library_root"]["default"] == ""
    assert "absolute" in fields["library_root"]["description"].lower()
    assert "libraryRoot" in fields["library_root"]["aliases"]

    first = app_client.post(
        "/api/v1/capabilities/get_api_surface",
        json={"limit": 1},
    ).json()
    second = app_client.post(
        "/api/v1/capabilities/get_api_surface",
        json={"offset": 1, "limit": 1},
    ).json()
    assert first["truncated"] is True
    assert first["next_offset"] == 1
    assert first["data"]["routes"][0]["path"] < second["data"]["routes"][0]["path"]

    constrained = app_client.post(
        "/api/v1/capabilities/get_api_surface",
        json={"path_contains": "/api/v1/diagnostics/export"},
    ).json()
    fields = {
        field["name"]: field for field in constrained["data"]["routes"][0]["fields"]
    }
    assert fields["limit"]["constraints"] == {"ge": 1, "le": 5000}

    queue = app_client.post(
        "/api/v1/capabilities/get_api_surface",
        json={"path_contains": "/api/v1/review/queue"},
    ).json()
    queue_route = queue["data"]["routes"][0]
    assert queue_route["request_model"] is None
    query = {field["name"]: field for field in queue_route["query_params"]}
    assert query["library_root"]["required"] is False
    assert query["item_status"]["aliases"] == ["status"]
    assert query["page_size"]["default"] == 50
    assert query["page_size"]["constraints"] == {"ge": 1, "le": 200}

    item = app_client.post(
        "/api/v1/capabilities/get_api_surface",
        json={"path_contains": "/api/v1/review/items/"},
    ).json()
    item_route = item["data"]["routes"][0]
    assert {field["name"] for field in item_route["path_params"]} == {
        "kind",
        "item_id",
    }
    assert all(field["required"] for field in item_route["path_params"])

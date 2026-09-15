"""HTTP contracts for the library "Groups" (collections) endpoints.

These protect the API shape the frontend (`frontend/src/api/http/library.ts`)
depends on: create/rename/list/delete and add/remove-document, including the
nested-tree form of `CollectionNode` and the cascade-delete of a subtree.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _import_doc(app_client: TestClient) -> str:
    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf", "application/pdf")},
    )
    assert resp.status_code == 200
    return resp.json()["document"]["doc_id"]


def _create_collection(
    app_client: TestClient, name: str, parent_id: str | None = None
) -> str:
    body: dict[str, object] = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    resp = app_client.post("/api/v1/library/collections/create", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["collection"]["collection_id"]


def test_collections_create_list_rename_delete_subtree(
    app_client: TestClient,
) -> None:
    """Creating a nested tree, listing it, renaming, and cascade deleting."""
    root_id = _create_collection(app_client, "Root")
    child_id = _create_collection(app_client, "Child", parent_id=root_id)

    resp = app_client.post("/api/v1/library/collections/list", json={})
    assert resp.status_code == 200
    nodes = resp.json()["collections"]
    assert len(nodes) == 1
    assert nodes[0]["collection_id"] == root_id
    assert nodes[0]["name"] == "Root"
    assert nodes[0]["doc_count"] == 0
    assert [c["collection_id"] for c in nodes[0]["children"]] == [child_id]

    resp = app_client.post(
        "/api/v1/library/collections/rename",
        json={"collection_id": root_id, "name": "Renamed"},
    )
    assert resp.status_code == 200

    # Deleting the root must also remove the nested child.
    resp = app_client.post(
        "/api/v1/library/collections/delete", json={"collection_id": root_id}
    )
    assert resp.status_code == 200
    resp = app_client.post("/api/v1/library/collections/list", json={})
    assert resp.json()["collections"] == []


def test_collections_add_remove_document_tracks_doc_count(
    app_client: TestClient,
) -> None:
    """Attaching/detaching a real document updates the listed doc_count."""
    doc_id = _import_doc(app_client)
    collection_id = _create_collection(app_client, "Papers")

    def _doc_count() -> int:
        resp = app_client.post("/api/v1/library/collections/list", json={})
        assert resp.status_code == 200
        return resp.json()["collections"][0]["doc_count"]

    assert _doc_count() == 0
    resp = app_client.post(
        "/api/v1/library/collections/add-document",
        json={"collection_id": collection_id, "doc_id": doc_id},
    )
    assert resp.status_code == 200
    assert _doc_count() == 1

    resp = app_client.post(
        "/api/v1/library/collections/remove-document",
        json={"collection_id": collection_id, "doc_id": doc_id},
    )
    assert resp.status_code == 200
    assert _doc_count() == 0


def test_collections_create_rejects_blank_name(
    app_client: TestClient,
) -> None:
    resp = app_client.post(
        "/api/v1/library/collections/create",
        json={"name": "   "},
    )
    assert resp.status_code == 422


def test_collections_add_document_to_unknown_collection_returns_404(
    app_client: TestClient,
) -> None:
    doc_id = _import_doc(app_client)
    resp = app_client.post(
        "/api/v1/library/collections/add-document",
        json={"collection_id": "does-not-exist", "doc_id": doc_id},
    )
    assert resp.status_code == 404


def test_collections_add_unknown_document_returns_404(
    app_client: TestClient,
) -> None:
    collection_id = _create_collection(app_client, "Papers")
    resp = app_client.post(
        "/api/v1/library/collections/add-document",
        json={"collection_id": collection_id, "doc_id": "no-such-doc"},
    )
    assert resp.status_code == 404

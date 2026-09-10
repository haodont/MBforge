"""Unit tests for notes endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_NOTE = {
    "id": "n1",
    "title": "Note",
    "content": "content",
    "tags": ["tag1"],
    "links": [{"type": "note", "refId": "n2", "refTitle": "Other"}],
    "createdAt": "2024-01-01",
    "updatedAt": "2024-01-02",
}


@pytest.mark.parametrize(
    "case",
    ["library_root_alias", "camel_case_note_fields", "doc_id_alias"],
)
def test_notes_accepts_frontend_aliases(
    app_client: TestClient, tmp_library: Path, case: str
) -> None:
    """The frontend alias shapes (libraryRoot, camelCase fields, doc_id) work."""
    root = str(tmp_library)
    if case == "library_root_alias":
        resp = app_client.post("/api/v1/notes/list", json={"libraryRoot": root})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
    elif case == "camel_case_note_fields":
        resp = app_client.post(
            "/api/v1/notes/save",
            json={
                "library_root": root,
                "note": {
                    "id": "n-alias",
                    "title": "Alias",
                    "content": "c",
                    "tags": [],
                    "links": [{"type": "note", "refId": "n2", "refTitle": "Other"}],
                    "createdAt": "2024-01-01",
                    "updatedAt": "2024-01-02",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["note"]["id"] == "n-alias"
        assert data["note"]["createdAt"] == "2024-01-01"
    else:
        resp = app_client.post(
            "/api/v1/notes/save",
            json={"library_root": root, "note": {**_NOTE, "id": "n-doc"}},
        )
        assert resp.status_code == 200
        resp = app_client.post(
            "/api/v1/notes/get",
            json={"library_root": root, "doc_id": "n-doc"},
        )
        assert resp.status_code == 200
        assert resp.json()["notes"] == "content"


def test_notes_crud_flow(app_client: TestClient, tmp_library: Path) -> None:
    """Save, list, get, delete, and list again end-to-end."""
    resp = app_client.post(
        "/api/v1/notes/save",
        json={"library_root": str(tmp_library), "note": _NOTE},
    )
    assert resp.status_code == 200
    saved = resp.json()["note"]
    assert saved["id"] == "n1"
    assert saved["title"] == "Note"
    assert saved["createdAt"] == "2024-01-01"

    resp = app_client.post(
        "/api/v1/notes/list", json={"library_root": str(tmp_library)}
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert len(resp.json()["notes"]) == 1

    resp = app_client.post(
        "/api/v1/notes/get",
        json={"library_root": str(tmp_library), "id": "n1"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "content"

    resp = app_client.post(
        "/api/v1/notes/delete",
        json={"library_root": str(tmp_library), "id": "n1"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = app_client.post(
        "/api/v1/notes/list", json={"library_root": str(tmp_library)}
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == []


def test_notes_backlinks_find_linked_notes(
    app_client: TestClient, tmp_library: Path
) -> None:
    target = {**_NOTE, "id": "target", "links": []}
    source = {
        **_NOTE,
        "id": "source",
        "links": [{"type": "note", "refId": "target", "refTitle": "Target"}],
    }
    app_client.post(
        "/api/v1/notes/save",
        json={"library_root": str(tmp_library), "note": target},
    )
    app_client.post(
        "/api/v1/notes/save",
        json={"library_root": str(tmp_library), "note": source},
    )

    resp = app_client.post(
        "/api/v1/notes/backlinks",
        json={"library_root": str(tmp_library), "targetId": "target"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["backlinks"]) == 1
    assert data["backlinks"][0]["id"] == "source"


def test_notes_error_response_has_error_code(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A mismatched library_root surfaces an MBForgeError with an error_code."""
    resp = app_client.post(
        "/api/v1/notes/list",
        json={"library_root": str(tmp_library / "nonexistent")},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert body["error_code"] == "invalid_path"

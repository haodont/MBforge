from __future__ import annotations

from fastapi.testclient import TestClient

from mbforge.app import create_app
from mbforge.routers import agent


def test_agent_molecule_tool_resolves_library_server_side(monkeypatch) -> None:
    """The public tool contract must not let the model choose a library path."""

    captured: dict[str, object] = {}

    monkeypatch.setattr(agent, "resolve_library_root", lambda _: "C:/library")

    def fake_search(root: str, query: str, **kwargs):
        captured.update(root=root, query=query, kwargs=kwargs)
        return [{"mol_id": "M-1", "canonical_smiles": "CCO"}]

    monkeypatch.setattr(agent, "search_molecules", fake_search)

    response = TestClient(create_app()).post(
        "/api/v1/agent/tools/molecule-search",
        json={"query": "ethanol", "top_k": 1},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"mol_id": "M-1", "canonical_smiles": "CCO"}
    ]
    assert captured == {
        "root": "C:/library",
        "query": "ethanol",
        "kwargs": {
            "top_k": 1,
            "mode": "auto",
            "similarity_threshold": 0.5,
        },
    }

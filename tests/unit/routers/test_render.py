"""Unit tests for molecule rendering endpoints."""

from __future__ import annotations

import asyncio

from mbforge.application.dto.common import MoleculeRenderRequest
from mbforge.interfaces.http.system.models import render_molecule


def test_render_molecule_rejects_empty_smiles_at_route_level() -> None:
    """Empty input is rejected before any thread offload."""
    result = asyncio.run(render_molecule(MoleculeRenderRequest(smiles="")))
    assert result.success is False
    assert result.error == "smiles required"

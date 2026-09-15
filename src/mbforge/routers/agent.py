"""Tool endpoints for the frontend-hosted MBForge agent."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services.molecule.queries import search_molecules
from ._path_utils import resolve_library_root

router = APIRouter()


class AgentMoleculeSearchRequest(BaseModel):
    """Safe tool input: the active library is resolved server-side."""

    query: str = Field(..., min_length=1, max_length=512)
    mode: Literal["auto", "text", "substructure", "similarity"] = "auto"
    top_k: int = Field(10, ge=1, le=20)
    similarity_threshold: float = Field(0.5, ge=0.0, le=1.0)


class AgentMoleculeSearchResponse(BaseModel):
    success: bool = True
    tool: Literal["molecule_search"] = "molecule_search"
    results: list[dict] = Field(default_factory=list)


@router.post("/tools/molecule-search", response_model=AgentMoleculeSearchResponse)
async def agent_molecule_search(
    body: AgentMoleculeSearchRequest,
) -> AgentMoleculeSearchResponse:
    """Search the configured library for the frontend LLM."""

    results = await asyncio.to_thread(
        search_molecules,
        str(resolve_library_root(None)),
        body.query,
        top_k=body.top_k,
        mode=body.mode,
        similarity_threshold=body.similarity_threshold,
    )
    return AgentMoleculeSearchResponse(results=results)

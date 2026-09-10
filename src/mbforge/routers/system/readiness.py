"""Readiness diagnostics endpoints — aggregated environment probes.

Thin endpoint layer over :mod:`mbforge.services.system.readiness`; includes the
legacy ``/diagnostics`` compatibility surface.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...models.readiness import (
    DemoRunResponse,
    LLMProbeResponse,
    ReadinessSummaryResponse,
)
from ...services.system import readiness as readiness_service

router = APIRouter()
diagnostics_router = APIRouter()


@router.get("/readiness/summary")
async def readiness_summary() -> ReadinessSummaryResponse:
    """Aggregate read-only probes for library, database, models, LLM, OCR."""
    return await readiness_service.summary()


@router.post("/readiness/probe-llm")
async def readiness_probe_llm() -> LLMProbeResponse:
    """Live LLM probe: send a 1-token request with a 15s timeout."""
    return await readiness_service.probe_llm()


@router.post("/readiness/demo-run")
async def readiness_demo_run() -> DemoRunResponse:
    """Generate a demo PDF and enqueue it via the standard ingest path."""
    return await readiness_service.demo_run()


@diagnostics_router.get("/summary")
async def diagnostics_summary() -> ReadinessSummaryResponse:
    """Compatibility endpoint for the Settings diagnostics center."""
    return await readiness_service.summary()


@diagnostics_router.post("/probe-llm")
async def diagnostics_probe_llm() -> LLMProbeResponse:
    """Compatibility endpoint for the Settings diagnostics center."""
    return await readiness_service.probe_llm()


@diagnostics_router.post("/demo-run")
async def diagnostics_demo_run() -> DemoRunResponse:
    """Compatibility endpoint for the Settings diagnostics center."""
    return await readiness_service.demo_run()

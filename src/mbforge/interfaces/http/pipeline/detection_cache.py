"""Detection cache endpoints — molecule_detections table under library DB.

Canonical FE surface for read / clear / stats. Endpoints validate requests
and delegate to :mod:`mbforge.application.use_cases.pipeline.detection_cache`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from mbforge.application.dto.detection_cache import (
    BatchScanResponse,
    CachedDetectionsResponse,
    ClearResponse,
    DetectionBatchScanRequest,
    DetectionClearDocRequest,
    DetectionClearRequest,
    DetectionExtractPageRequest,
    DetectionGetRequest,
    DetectionSaveRequest,
    DetectionStatsRequest,
    SaveResponse,
    StatsResponse,
)
from mbforge.application.use_cases.pipeline import detection_cache as cache_service
from mbforge.foundation.logger import get_logger
from mbforge.interfaces.http._path_utils import resolve_library_root, validate_doc_id

logger = get_logger("mbforge.detection_cache")

router = APIRouter()


@router.post("/get", response_model=CachedDetectionsResponse)
async def detection_get(body: DetectionGetRequest) -> CachedDetectionsResponse:
    root_path = resolve_library_root(body.library_root)
    validate_doc_id(body.doc_id)
    result = await asyncio.to_thread(
        cache_service.load_cached_detections, str(root_path), body.doc_id, body.page
    )
    return CachedDetectionsResponse(**result)


@router.post("/save", response_model=SaveResponse)
async def detection_save(body: DetectionSaveRequest) -> SaveResponse:
    if not body.detections:
        return SaveResponse(success=False, error="detections required")

    root_path = resolve_library_root(body.library_root)
    for det in body.detections:
        validate_doc_id(det.doc_id)

    detections = [det.model_dump() for det in body.detections]
    await asyncio.to_thread(cache_service.save_detections, str(root_path), detections)
    return SaveResponse(success=True)


@router.post("/extract-page", response_model=CachedDetectionsResponse)
async def detection_extract_page(
    body: DetectionExtractPageRequest,
) -> CachedDetectionsResponse:
    """Cache-aware single-page read (no inference).

    Live detect remains ``POST /api/v1/moldet/extract-pdf``. This endpoint only
    returns rows already in ``molecule_detections``.
    """
    root_path = resolve_library_root(body.library_root)
    validate_doc_id(body.doc_id)
    result = await asyncio.to_thread(
        cache_service.load_cached_detections, str(root_path), body.doc_id, body.page
    )
    return CachedDetectionsResponse(**result)


@router.post("/stats", response_model=StatsResponse)
async def detection_stats(body: DetectionStatsRequest) -> StatsResponse:
    root_path = resolve_library_root(body.library_root)
    try:
        result = await asyncio.to_thread(cache_service.read_stats, str(root_path))
        return StatsResponse(**result)
    except Exception as e:
        logger.warning("Failed to read detection cache stats: %s", e)
        return StatsResponse()


@router.post("/clear", response_model=ClearResponse)
async def detection_clear(body: DetectionClearRequest) -> ClearResponse:
    root_path = resolve_library_root(body.library_root)
    try:
        cleared = await asyncio.to_thread(cache_service.clear_all, str(root_path))
        return ClearResponse(success=True, cleared=cleared)
    except Exception as e:
        logger.warning("Failed to clear detection cache: %s", e)
        return ClearResponse(success=True, cleared=0)


@router.post("/clear-doc", response_model=ClearResponse)
async def detection_clear_doc(
    body: DetectionClearDocRequest,
) -> ClearResponse:
    root_path = resolve_library_root(body.library_root)
    validate_doc_id(body.doc_id)
    try:
        cleared = await asyncio.to_thread(
            cache_service.clear_doc, str(root_path), body.doc_id
        )
        return ClearResponse(success=True, cleared=cleared)
    except Exception as e:
        logger.warning("Failed to clear detection cache for doc: %s", e)
        return ClearResponse(success=True, cleared=0)


@router.post("/batch-scan", response_model=BatchScanResponse)
async def detection_batch_scan(
    body: DetectionBatchScanRequest,
) -> BatchScanResponse:
    """Batch quick MoldDet scan — not implemented; fail closed."""
    return BatchScanResponse()

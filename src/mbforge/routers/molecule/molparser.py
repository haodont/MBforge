"""MolParser-Mobile structure recognition endpoints.

Wraps the local MolParser backend to accept base64-encoded molecule images
and return predicted Layer-1 SMILES + Layer-2 E-SMILES.
``POST /recognize`` additionally preprocesses the crop and reads compound
identifiers (``coref``) off the offcut fragments with local RapidOCR.
Loaded on first request; the model status is surfaced through the sidecar
health endpoints.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Request

from ...backends import molparser
from ...infra.models import ensure as ensure_model_status
from ...pipeline.detection.recognition import recognize_molecule
from ...utils.errors import ModelNotAvailableError, ValidationError
from ...utils.files import decode_base64_to_tempfile
from ...utils.logger import get_logger

logger = get_logger("mbforge.routers.molparser")

router = APIRouter()


async def _image_from_request(request: Request):
    """Decode the request body into a fully-loaded PIL image.

    Accepts raw grayscale bytes (``application/octet-stream`` with
    ``X-Image-Width`` / ``X-Image-Height``) or a JSON body with a base64
    encoded image file. The temp file backing a base64 upload is deleted
    before return; the image is forced into memory first.
    """
    import numpy as np
    from PIL import Image

    content_type = request.headers.get("content-type", "")

    if content_type == "application/octet-stream":
        width = int(request.headers.get("x-image-width", "0"))
        height = int(request.headers.get("x-image-height", "0"))
        if width <= 0 or height <= 0:
            raise ValidationError("X-Image-Width and X-Image-Height required")
        raw_bytes = await request.body()
        arr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(height, width)
        return Image.fromarray(arr, "L")

    body = await request.json()
    image_base64 = body.get("image_base64", "")
    if not image_base64:
        raise ValidationError("image_base64 is required")
    ext = body.get("ext", "png")
    tmp_path = decode_base64_to_tempfile(image_base64, ext)
    try:
        image = Image.open(tmp_path)
        image.load()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return image


@router.post("")
async def molparser_predict(request: Request) -> dict[str, Any]:
    """Predict E-SMILES (+ Layer-1 SMILES) from molecule image."""
    image = await _image_from_request(request)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, molparser.load)
    result = await loop.run_in_executor(None, lambda: molparser.predict(image))
    if not result.smiles:
        err_msg = result.properties.get("error", "unknown error")
        raise ModelNotAvailableError(f"MolParser not available: {err_msg}")
    ensure_model_status("molparser", "ready")
    return {
        "esmiles": result.esmiles,
        "smiles": result.smiles,
        "success": True,
    }


@router.post("/recognize")
async def molparser_recognize(request: Request) -> dict[str, Any]:
    """Unified crop recognition: preprocess, then MolParser + OCR labels."""
    image = await _image_from_request(request)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: recognize_molecule(image))
    if not result.smiles:
        raise ModelNotAvailableError(
            "MolParser not available: model missing or recognition failed"
        )
    ensure_model_status("molparser", "ready")
    return {
        "esmiles": result.esmiles,
        "smiles": result.smiles,
        "coref": result.coref,
        "coref_primary": result.coref_primary,
        "success": True,
    }

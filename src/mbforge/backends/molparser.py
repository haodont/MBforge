"""MolParser-Mobile backend — chemical structure image → E-SMILES.

Wraps the MolParser-Mobile recognition model (transformers custom
``MolParserVisionEncoderDecoderModel``, trust_remote_code) to convert molecule
crops into MBForge's three-layer representation:

- ``ExtractionResult.smiles``  — Layer 1 plain SMILES（RDKit 可解析）
- ``ExtractionResult.esmiles`` — Layer 2 full E-SMILES（``SMILES<sep>EXTENSION``）

The model is loaded lazily on first request; ``predict`` and ``predict_batch``
expose synchronous entry points routers can call without blocking the event
loop. When weights are missing, ``load`` auto-fetches them on first use via
``ResourceManager.ensure("molparser")`` (ModelScope-first, HuggingFace
fallback), mirroring the moldet self-ensure path.
"""

from __future__ import annotations

import threading

import numpy as np
from PIL import Image

from ..core.detection.types import ExtractionResult
from ..utils.logger import get_logger
from .device import is_gpu_available

logger = get_logger(__name__)

_MODEL = None
_AVAILABLE: bool = False
_ERROR: str = ""
_LOAD_LOCK = threading.Lock()
# transformers ``generate`` is not guaranteed thread-safe across asyncio worker
# threads; serialize all calls into the recognizer. Use the shared GPU gate so
# MolDet and MolParser do not compete for VRAM simultaneously.


def _get_gpu_gate():
    """Lazy import to avoid circular dependency at module load time."""
    from ..infra.process import gpu_gate

    return gpu_gate()


def _strip_trailing_sep(esmiles: str) -> str:
    """MolParser 的 ``esmi`` 对无标签分子追加孤立 ``<sep>``；MBForge 规范
    （docs/wiki/esmiles.md）要求无扩展时退化为纯 SMILES，故剥离尾部 ``<sep>``。"""
    return esmiles[:-5] if esmiles.endswith("<sep>") else esmiles


def load(device: str | None = None) -> None:
    """Lazy-load MolParser-Mobile model (thread-safe)."""
    global _MODEL, _AVAILABLE, _ERROR
    if _MODEL is not None:
        return
    with _LOAD_LOCK:
        if _MODEL is not None:
            return

        logger.info("Loading MolParser-Mobile model...")
        try:
            from ..infra.resource_manager import ResourceManager

            path = ResourceManager.get_molparser_path()
            if path is None:
                # Auto-fetch weights on first use when missing, mirroring
                # moldet's self-ensure. ensure() is idempotent and a fast
                # no-op when the weights are already present.
                logger.info(
                    "MolParser-Mobile weights missing; auto-downloading "
                    "(ModelScope UniParser/MolParser-Mobile, HF fallback)..."
                )
                ResourceManager.ensure("molparser")
                path = ResourceManager.get_molparser_path()
            if path is None:
                _AVAILABLE = False
                _ERROR = (
                    "MolParser-Mobile model not found after auto-download "
                    "(check network / ModelScope). Place model files in "
                    "~/MBForge/models/MolParser-Mobile/ or retry download "
                    "from Settings."
                )
                logger.warning(_ERROR)
                return

            logger.info("MolParser model path: %s", path)
            dev = device or ("cuda" if is_gpu_available() else "cpu")
            logger.info("Loading MolParser on device: %s", dev)

            # Initialize CUDA context in the loading thread to avoid issues
            # when the model is first used in a different worker thread.
            if dev == "cuda":
                import torch

                logger.info("Initializing CUDA context for MolParser")
                dummy_tensor = torch.zeros(1, 1).cuda()
                del dummy_tensor
                torch.cuda.synchronize()
                logger.info("CUDA context initialized")

            from molparser.models.runtime import MolParserRecognizer

            _MODEL = MolParserRecognizer(str(path), device=dev)
            _AVAILABLE = True
            logger.info("MolParser-Mobile loaded successfully on %s", dev)
        except Exception as exc:
            _ERROR = str(exc)
            _AVAILABLE = False
            logger.error("MolParser-Mobile load failed: %s", exc, exc_info=True)


def unload() -> None:
    """Release model."""
    global _MODEL, _AVAILABLE, _ERROR
    _MODEL = None
    _AVAILABLE = False
    _ERROR = ""


def health() -> dict[str, str]:
    return {
        "status": "ready" if _AVAILABLE else ("error" if _ERROR else "loading"),
        "error": _ERROR,
    }


def _result_from_caption(caption: str) -> ExtractionResult:
    """postprocess 原始 caption → Layer1 smiles + Layer2 esmiles."""
    from molparser.utils import postprocess_caption

    pp = postprocess_caption(caption) or {}
    markush = pp.get("markush") is True
    properties = {"markush": markush}
    if markush:
        properties["groups"] = pp.get("groups", "")
    return ExtractionResult(
        esmiles=_strip_trailing_sep(pp.get("esmi") or ""),
        smiles=pp.get("smi") or "",
        properties=properties,
    )


def _error_result(error: str) -> ExtractionResult:
    return ExtractionResult(
        esmiles="",
        smiles="",
        properties={"error": error},
    )


def predict(image: Image.Image | np.ndarray) -> ExtractionResult:
    """Predict single image."""
    # Lazy-load model on first use
    if _MODEL is None:
        load()
    if not _AVAILABLE or _MODEL is None:
        return _error_result(_ERROR or "model not available")
    try:
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image)
        with _get_gpu_gate():
            caption = _MODEL.recognize([image])[0]
        return _result_from_caption(caption)
    except Exception as exc:
        logger.warning("MolParser predict failed: %s", exc)
        return _error_result(str(exc))


def predict_batch(
    images: list[Image.Image | np.ndarray],
) -> list[ExtractionResult]:
    """Predict a batch of crops in a single backend call."""
    # Lazy-load model on first use
    if _MODEL is None:
        load()
    if not _AVAILABLE or _MODEL is None:
        error = _ERROR or "model not available"
        return [_error_result(error) for _ in images]

    try:
        pil_images: list[Image.Image] = []
        for image in images:
            if isinstance(image, np.ndarray):
                image = Image.fromarray(image)
            pil_images.append(image)
        with _get_gpu_gate():
            results = _MODEL.recognize(pil_images)
        return [_result_from_caption(caption) for caption in results]
    except Exception as exc:
        logger.warning("MolParser predict_batch failed: %s", exc)
        return [_error_result(str(exc)) for _ in images]

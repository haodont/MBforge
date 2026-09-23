"""Crop-label OCR — read compound identifiers off molecule crop offcuts.

MolDet crop boxes routinely capture printed labels next to the drawn
structure (compound numbers like ``4A``/``8b``, Roman-style ids like
``II``/``I-1``, group formulas like ``CF3``/``NH``, stereo markers like ``(R)``).
These come from the DBSCAN
"others" image (see the pipeline ``detection.image_preprocessing`` module)
and are read locally with RapidOCR. The engine is selected by
``moldet.ocr_engine``:

- ``onnx`` (default): rapidocr_onnxruntime on CPU.
- ``torch``: rapidocr v3 TORCH engine on CUDA, wrapped in the shared GPU
  gate so it does not race MolDet/MolParser for VRAM.

The engine is created once **per thread** and reused (thread-local), so the
pipeline may read labels concurrently from its bounded OCR pool without
sharing a single non-thread-safe engine. The MolDet-style lifecycle
(singleton / unload / health) is exposed by ``label_reader``.
"""

from __future__ import annotations

import re
import threading

import numpy as np
from PIL import Image

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

# Module-level engine, used when injected (tests) or as the legacy single
# default. When ``None`` each thread lazily creates its own engine.
_ENGINE = None
_thread_engines = threading.local()

# Compound-identifier whitelist. Patent schemes usually number compounds
# digit-leading (``1a``, ``4A``, ``10B``, ``11-a``), but some use Roman-style
# ids (``I``, ``II``, ``I-1``); everything else OCR
# reads off a crop is structure content (``NH``, ``CF3``, ``N-N``), stereo
# markers (``(R)``, ``(S)`` + mangled variants), R-group placeholders
# (``R1``) or reagent text (``TBAF``) — see the survey over
# tests/moldet_comparison_crops (5123 reads, 267 passed the old shape
# filter, ~all noise).
# ponytail: whitelist still rejects arbitrary letter-leading ids (``A-1``
# style); labels are enrichment only — a miss falls back to existing
# name/SMILES matching.
_IDENTIFIER_PATTERN = re.compile(
    r"^(?:\d+[A-Za-z]?(?:-[A-Za-z0-9]{1,3})?|(?=[IVXLCDM]*[IVX])[IVXLCDM]+(?:-[A-Za-z0-9]{1,3})?)$",
    re.IGNORECASE,
)
_MIN_CONFIDENCE = 0.9


def _engine_name() -> str:
    """Return the configured OCR engine name (``onnx`` or ``torch``)."""
    try:
        from mbforge.foundation.config import load_global_config

        cfg = load_global_config()
        moldet = getattr(cfg, "moldet", None)
        name = getattr(moldet, "ocr_engine", "torch") if moldet is not None else "torch"
        return (name or "torch").lower()
    except Exception:
        return "torch"


def _fallback_enabled() -> bool:
    """Whether an unavailable torch engine may fall back to onnxruntime CPU."""
    try:
        from mbforge.foundation.config import load_global_config

        cfg = load_global_config()
        moldet = getattr(cfg, "moldet", None)
        if moldet is None:
            return True
        return bool(getattr(moldet, "ocr_engine_fallback", True))
    except Exception:
        return True


def _ocr_mode() -> str:
    """Return the configured OCR deployment mode (``inprocess`` or ``daemon``)."""
    try:
        from mbforge.foundation.config import load_global_config

        cfg = load_global_config()
        moldet = getattr(cfg, "moldet", None)
        mode = (
            getattr(moldet, "ocr_mode", "inprocess")
            if moldet is not None
            else "inprocess"
        )
        return (mode or "inprocess").lower()
    except Exception:
        return "inprocess"


def _try_onnx():
    """Return a rapidocr_onnxruntime engine, or ``None`` if the package is missing."""
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()
    except Exception as exc:
        logger.warning(
            "onnxruntime OCR backend unavailable (%s); crop-label OCR disabled", exc
        )
        return None


def _create_engine(name: str, device_id: int = 0):
    """Create the engine for ``name``; returns ``None`` when unavailable.

    - ``torch``: rapidocr v3 TORCH engine on CUDA (the primary, measured fast
      path). If CUDA/torch is unavailable and fallback is enabled AND
      onnxruntime is installed, falls back to onnx.
    - ``onnx``: rapidocr_onnxruntime CPU engine, or ``None`` if the package is
      missing (never forward-falls to torch).

    Never raises for a missing backend — OCR enrichment is allowed to be empty.
    ``device_id`` selects the CUDA device for the torch engine (used by the
    persistent-daemon path so OCR can sit on a dedicated/secondary GPU rather
    than competing with MolDet/MolParser on device 0).
    """
    if name == "torch":
        try:
            import torch

            if torch.cuda.is_available():
                from rapidocr import EngineType, RapidOCR

                return RapidOCR(
                    params={
                        "Det.engine_type": EngineType.TORCH,
                        "Cls.engine_type": EngineType.TORCH,
                        "Rec.engine_type": EngineType.TORCH,
                        "EngineConfig.torch.use_cuda": True,
                        "EngineConfig.torch.cuda_ep_cfg.device_id": device_id,
                    }
                )
        except Exception as exc:
            logger.warning("torch OCR engine unavailable (%s)", exc)
        if _fallback_enabled():
            onnx_engine = _try_onnx()
            if onnx_engine is not None:
                return onnx_engine
        return None
    return _try_onnx()


def _get_engine():
    """Return the injected/module engine, else this thread's lazy singleton.

    An injected ``_ENGINE`` (tests, single-threaded) is honored first; when
    it is ``None``, each caller thread lazily creates and reuses its own
    RapidOCR engine so concurrent pool workers are independent.
    """
    if _ENGINE is not None:
        return _ENGINE
    engine = getattr(_thread_engines, "engine", None)
    if engine is None:
        name = _engine_name()
        engine = _create_engine(name)
        _thread_engines.engine = engine
        _thread_engines.name = name
    return engine


def engine_name() -> str:
    """The engine name in use on the calling thread (``onnx``/``torch``)."""
    if _ENGINE is not None:
        return "onnx"
    name = getattr(_thread_engines, "name", None)
    return name or _engine_name()


def _clear_engines() -> None:
    """Drop all cached engines (module singleton + per-thread) for unload."""
    global _ENGINE
    _ENGINE = None
    _thread_engines.engine = None
    _thread_engines.name = None


def _is_label(text: str, conf: float) -> bool:
    value = (text or "").strip()
    return conf >= _MIN_CONFIDENCE and _IDENTIFIER_PATTERN.match(value) is not None


def filter_label_texts(reads: list[tuple[str, float]]) -> list[str]:
    """Reduce raw OCR reads to compound-identifier strings.

    Keeps digit-leading and Roman-style identifiers (``4A``, ``8b``, ``II``,
    ``I-1``) above the confidence floor, drops everything else (atom/group
    formulas read off the drawn structure, stereo/R-group markers, prose,
    low-confidence noise). Order preserved, duplicates removed.
    """
    labels: list[str] = []
    for text, conf in reads:
        if not _is_label(text, conf):
            continue
        value = text.strip()
        if value not in labels:
            labels.append(value)
    return labels


def _tight_box(points) -> tuple[int, int, int, int]:
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _isolation_flags(boxes: list[tuple[int, int, int, int]]) -> list[bool]:
    """Flag reads that stand alone on their text line.

    A read is *not* isolated when another read's baseline band overlaps it
    (>30% of the smaller height) within 3× its height horizontally — i.e.
    it is part of a longer text line (body prose, next scheme entry) rather
    than a standalone compound-number print.
    # ponytail: heuristic window (3× height); a true number sharing a line
    with prose ("21 is ...") gets demoted — add letter-content checks only
    if a real document hits it.
    """
    flags = [True] * len(boxes)
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        for j, (a0, b0, a1, b1) in enumerate(boxes):
            if i == j:
                continue
            overlap = min(y1, b1) - max(y0, b0)
            if overlap <= 0.3 * min(y1 - y0, b1 - b0):
                continue
            gap = max(a0 - x1, x0 - a1)
            if gap < 3 * (y1 - y0):
                flags[i] = False
                break
    return flags


def _raw_reads(result) -> list:
    """Normalize a RapidOCR result into ``[points, text, conf]`` reads.

    Backends differ in return shape and this must never crash the OCR path:
      - rapidocr_onnxruntime / rapidocr v2 (and v3 when a tuple is still
        returned): a bare reads list ``[[points, text, conf], ...]``, or a
        ``(reads_list, elapse)`` tuple.
      - rapidocr v3 torch: a ``RapidOCROutput`` object with ``.boxes``,
        ``.txts``, ``.scores`` attributes.
    Recognition keys off "all elements are read entries" instead of the tuple
    length: an offcut returning exactly two reads is still a bare reads list,
    not the ``(reads, elapse)`` form. Unknown shapes yield ``[]``.
    """
    if result is None:
        return []

    # Object form: v3 RapidOCROutput (datum: boxes, txts, scores).
    if hasattr(result, "txts") or hasattr(result, "boxes"):
        boxes = result.boxes
        txts = result.txts
        scores = result.scores
        if txts is None or boxes is None or scores is None:
            return []
        return [
            [list(b), str(t), float(c)]
            for b, t, c in zip(boxes, txts, scores, strict=False)
        ]

    # Container form: rebuild a normalized reads list from whatever nests the
    # read entries (bare list, or (reads, elapse) tuple).
    reads = []
    for item in result:
        if _is_read_entry(item):
            reads.append(_unpack_read(item))
        elif isinstance(item, (list, tuple)):
            # Possibly the reads_list inside a (reads, elapse) tuple.
            for inner in item:
                if _is_read_entry(inner):
                    reads.append(_unpack_read(inner))
    return reads


def _is_read_entry(entry) -> bool:
    # A single read is [points, text, conf] where points is a box (list) and
    # text/conf are scalars. A bare reads list or the reads_list inside a
    # (reads, elapse) tuple fails this: its own element[1] is another read's
    # box (a list), not a text string.
    return (
        isinstance(entry, (list, tuple))
        and len(entry) >= 3
        and isinstance(entry[0], (list, tuple))
        and isinstance(entry[1], str)
        and not isinstance(entry[-1], (list, tuple, dict))
    )


def _unpack_read(entry) -> list:
    """Return ``[points, text, conf]`` from a read entry.

    onnxruntime / v2 read shape is ``[points, text, conf]`` but may carry extra
    trailing elements on some offcuts; the tuple-path box is always the first
    element and ``(text, conf)`` the last two, so take them positionally robustly.
    """
    points = list(entry[0])
    text = str(entry[1])
    conf = float(entry[-1])
    return [points, text, conf]


def _label_reads_from_result(
    result,
) -> list[tuple[str, float, tuple[int, int, int, int], bool]]:
    """Post-process raw RapidOCR output into identifier reads.

    Handles both the tuple form (onnxruntime / v2) and the v3 ``RapidOCROutput``
    object. Shared by the in-process path and the OCR daemon so both produce
    identical (``text, conf, bbox, isolated``) results. Never crashes on unknown
    output shapes — labels are enrichment only.
    """
    raw = _raw_reads(result)
    flags = _isolation_flags([_tight_box(points) for points, _, _ in raw])
    reads: list[tuple[str, float, tuple[int, int, int, int], bool]] = []
    for (points, text, conf), isolated in zip(raw, flags, strict=True):
        if not _is_label(text, float(conf)):
            continue
        value = text.strip()
        if any(value == seen for seen, _, _, _ in reads):
            continue
        reads.append((value, float(conf), _tight_box(points), isolated))
    return reads


def extract_label_reads(
    image: Image.Image,
) -> list[tuple[str, float, tuple[int, int, int, int], bool]]:
    """OCR an "others" image; return identifier-like reads with positions.

    Each read is ``(text, confidence, (x0, y0, x1, y1), isolated)`` where
    the bbox is the tight pixel box on the input image and ``isolated``
    marks standalone prints (false = part of a longer text line). Empty
    list when RapidOCR is unavailable or the engine fails — labels are
    enrichment, never worth failing the extraction.
    """
    try:
        engine = _get_engine()
        if engine is None:
            return []
        from mbforge.adapters.runtime.process import gpu_gate

        arr = np.asarray(image.convert("RGB"))
        if engine_name() == "torch":
            with gpu_gate():
                result = engine(arr)
        else:
            result, _ = engine(arr)
    except Exception as exc:  # noqa: BLE001 — OCR is enrichment; never fail the caller
        logger.warning("Crop-label OCR failed: %s", exc)
        return []
    return _label_reads_from_result(result)


def extract_label_texts(image: Image.Image) -> list[str]:
    """OCR an "others" image and return identifier-like label strings."""
    return [text for text, _, _, _ in extract_label_reads(image)]

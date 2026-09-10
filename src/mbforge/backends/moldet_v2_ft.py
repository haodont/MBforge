"""MolDetv2-YOLO26 molecule detection backend.

This module owns model loading, inference, normalized molecule results, and
API serialization. Coref identifier detection is not part of the current
backend (the legacy FT model's category 3 was removed by a separate task).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from mbforge.utils.config import load_global_config
from mbforge.utils.logger import get_logger

logger = get_logger(__name__)

# Raw detector box in pixel coordinates (top-left origin):
# (x1, y1, x2, y2, conf, category_id)
PixelBox = tuple[float, float, float, float, float, int]


# ---- Result types and API serialization ----


@dataclass
class MoleculeBbox:
    category_id: int
    bbox: tuple[float, float, float, float]
    score: float = 0.0


@dataclass
class MoleculeResult:
    bboxes: list[MoleculeBbox]


def to_api_dict(result: MoleculeResult) -> dict[str, Any]:
    return {
        "bboxes": [
            {
                "category_id": bbox.category_id,
                "bbox": list(bbox.bbox),
                "score": bbox.score,
            }
            for bbox in result.bboxes
        ],
    }


# ---- Ultralytics lazy import (avoid ImportError when not installed) ----

_ultralytics: Any | None = None


def default_model_dir() -> Path:
    """Return the shared model cache directory (unified constant)."""
    from mbforge.utils.paths import get_model_cache_dir

    cache_dir = Path(get_model_cache_dir())
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _has_ultralytics() -> bool:
    global _ultralytics
    if _ultralytics is None:
        try:
            import ultralytics

            _ultralytics = ultralytics
            return True
        except ImportError:
            return False
    return True


# ---- Detector ----


class MolDetv2Detector:
    """MolDetv2 (YOLO26) molecule detector.

    Input: full-page PDF render image (>= 300 DPI recommended).
    Output: molecule bboxes (``category_id=1``). Native MolDetv2 detects
    molecules only; coref identifier detection (the legacy FT model's
    category 3) is out of scope.
    """

    #: Default weight filename, relative to the model directory.
    DEFAULT_SUBPATH = "moldet_v2_yolo26n_960_doc.pt"

    def __init__(
        self,
        model_path: Path | None = None,
        device: str | None = None,
        conf_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        imgsz: int = 960,
    ) -> None:
        """Initialize the detector.

        Args:
            model_path: Model weights path; resolved via ResourceManager
                when ``None``.
            device: Inference device; ``None`` means auto.
            conf_threshold: Confidence threshold.
            iou_threshold: NMS IoU threshold.
            imgsz: YOLO inference input size (960 for the PDF doc model).
        """
        if not _has_ultralytics():
            raise RuntimeError(
                "ultralytics is not installed; the MolDetv2 detector cannot be "
                "used. Install it with: uv pip install ultralytics"
            )

        self.device = device or load_global_config().moldet.device
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.imgsz = imgsz

        self.model_path = model_path or self._resolve_model_path()
        self._load_model()

    def _resolve_model_path(self) -> Path:
        """Resolve the model path through ResourceManager."""
        from mbforge.infra.resource_manager import ResourceManager

        resolved = ResourceManager.resolve_model_for_backend(
            "moldet", subpath=self.DEFAULT_SUBPATH
        )
        if resolved is not None and resolved.exists():
            return resolved

        # Fallback: default model directory (matches the catalog local_name)
        return default_model_dir() / "MolDetv2" / self.DEFAULT_SUBPATH

    def _load_model(self) -> None:
        """Load the YOLO model (missing weights mark the detector unavailable)."""
        if not self.model_path.exists():
            logger.warning(
                "MolDetv2 model not found: %s (molecule detection unavailable)",
                self.model_path,
            )
            self.model = None
            return

        logger.info("Loading MolDetv2 model: %s", self.model_path)
        start = time.perf_counter()
        from ultralytics import YOLO

        self.model = YOLO(str(self.model_path))

        # Warmup
        _ = self.model.predict(
            np.zeros((960, 960, 3), dtype=np.uint8),
            verbose=False,
            device=self.device if self.device != "auto" else None,
        )
        logger.info("MolDetv2 model loaded in %.2fs", time.perf_counter() - start)

    def is_available(self) -> bool:
        """Whether the detector is usable (model loaded)."""
        return self.model is not None

    def _predict(self, images: list[Image.Image | np.ndarray]) -> list[Any] | None:
        return self.model.predict(
            images,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.imgsz,
            verbose=False,
            device=self.device if self.device != "auto" else None,
        )

    def detect(self, image: Image.Image | np.ndarray) -> list[PixelBox]:
        """Detect molecules on a full-page image.

        Args:
            image: PIL Image or numpy array (H, W, C).

        Returns:
            List of ``(x1, y1, x2, y2, conf, category_id)`` boxes in
            **image coordinates** (top-left origin, pixels). Native MolDetv2
            is single-class, so ``category_id`` is always 1 (molecule).
        """
        return self.detect_batch([image])[0]

    def detect_batch(
        self, images: list[Image.Image | np.ndarray], max_per_call: int = 0
    ) -> list[list[PixelBox]]:
        """Detect molecules on a batch of images (single/chunked GPU call).

        ultralytics' ``predict(list)`` feeds the whole list as one GPU batch
        (LoadPilAndNumpy yields all images at once), avoiding per-image
        launch overhead.

        Args:
            images: List of PIL Images / numpy arrays.
            max_per_call: Max images per ``model.predict`` call; 0 = no
                chunking.

        Returns:
            Per-image bbox lists in input order; each element is
            ``(x1, y1, x2, y2, conf, category_id)`` in pixel coordinates
            (top-left origin).
        """
        if not self.is_available():
            raise RuntimeError(f"MolDetv2 model not loaded: {self.model_path}.")

        if not isinstance(images, (list, tuple)):
            images = [images]
        cap = max(1, int(max_per_call)) if max_per_call else 0
        chunks = (
            [images[i : i + cap] for i in range(0, len(images), cap)]
            if cap
            else [list(images)]
        )

        grouped: list[list[PixelBox]] = []
        for chunk in chunks:
            results = self._predict(chunk)
            if not results:
                grouped.extend([] for _ in chunk)
                continue
            for r, im in zip(results, chunk, strict=True):
                # Image area for size filtering
                if hasattr(im, "width") and hasattr(im, "height"):
                    img_area = im.width * im.height
                else:
                    img_area = im.shape[0] * im.shape[1]

                boxes: list[PixelBox] = []
                if r.boxes is None:
                    grouped.append(boxes)
                    continue
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
                    conf = float(box.conf[0].cpu().item())

                    # Native MolDetv2 is single-class (molecule); map all
                    # detections to internal category_id=1.
                    category_id = 1

                    # Size filtering: drop boxes that are too small, too
                    # large, or extremely elongated.
                    w, h = x2 - x1, y2 - y1
                    area_ratio = (w * h) / img_area if img_area > 0 else 0
                    if area_ratio < 0.0001 or area_ratio > 0.5:
                        continue
                    if w > 0 and h > 0:
                        ratio = max(w / h, h / w)
                        if ratio > 10.0:
                            continue

                    boxes.append((x1, y1, x2, y2, conf, category_id))
                grouped.append(boxes)
        return grouped


# ---- Normalized detection API (pipeline boundary) ----


def _normalize_boxes(
    all_boxes: Iterable[PixelBox],
    img_w: float,
    img_h: float,
    mol_conf_threshold: float,
) -> list[MoleculeBbox]:
    """Pixel-coordinate boxes → normalized ``MoleculeBbox`` list (shared filter)."""
    inv_w = 1.0 / img_w if img_w > 0 else 0.0
    inv_h = 1.0 / img_h if img_h > 0 else 0.0
    bboxes: list[MoleculeBbox] = []
    for x1, y1, x2, y2, conf, category_id in all_boxes:
        if category_id != 1 or conf < mol_conf_threshold:
            continue
        bbox = (
            max(0.0, min(1.0, x1 * inv_w)),
            max(0.0, min(1.0, y1 * inv_h)),
            max(0.0, min(1.0, x2 * inv_w)),
            max(0.0, min(1.0, y2 * inv_h)),
        )
        bboxes.append(MoleculeBbox(category_id=1, bbox=bbox, score=conf))
    return bboxes


def _resolve_detector(
    detector: MolDetv2Detector | None,
) -> MolDetv2Detector | None:
    """Return a usable detector or ``None`` (with a warning logged)."""
    if detector is None:
        try:
            detector = get_moldet()
        except (ImportError, RuntimeError, OSError) as exc:
            logger.warning("MolDetv2 initialization failed: %s", exc)
            return None

    if not isinstance(detector, MolDetv2Detector):
        logger.warning("MolDetv2 unavailable, skipping detection")
        return None

    if not detector.is_available():
        logger.warning("MolDetv2 model not loaded, skipping detection")
        return None
    return detector


def detect_molecules(
    image: Image.Image,
    detector: MolDetv2Detector | None = None,
    mol_conf_threshold: float = 0.7,
) -> MoleculeResult:
    """Detect molecules and return normalized boxes for pipeline consumers.

    The detector emits pixel-coordinate boxes. This boundary preserves the
    existing result contract by converting them to normalized image
    coordinates and applying the molecule-level confidence filter.
    """
    resolved = _resolve_detector(detector)
    if resolved is None:
        return MoleculeResult(bboxes=[])

    from ..infra.process import gpu_gate

    with gpu_gate():
        all_boxes = resolved.detect(image)

    bboxes = _normalize_boxes(
        all_boxes, image.size[0], image.size[1], mol_conf_threshold
    )

    logger.info("moldet_v2_ft: mols=%d", len(bboxes))
    return MoleculeResult(bboxes=bboxes)


def detect_molecules_batch(
    images: list[Image.Image],
    detector: MolDetv2Detector | None = None,
    mol_conf_threshold: float = 0.7,
    max_per_call: int = 0,
) -> list[MoleculeResult]:
    """Batched ``detect_molecules``: one GPU call for the whole image list.

    Order is preserved 1:1 with the input list. Unavailable models degrade to
    one empty result per image (same contract as the single-image path).
    ``max_per_call`` chunks the list into multiple predict calls when > 0.
    """
    if not images:
        return []
    resolved = _resolve_detector(detector)
    if resolved is None:
        return [MoleculeResult(bboxes=[]) for _ in images]

    from ..infra.process import gpu_gate

    with gpu_gate():
        grouped = resolved.detect_batch(images, max_per_call=max_per_call)

    results = [
        MoleculeResult(
            bboxes=_normalize_boxes(
                boxes, image.size[0], image.size[1], mol_conf_threshold
            )
        )
        for boxes, image in zip(grouped, images, strict=True)
    ]
    logger.info(
        "moldet_v2_ft batch: imgs=%d mols=%d",
        len(images),
        sum(len(r.bboxes) for r in results),
    )
    return results


# ---- Process-wide singleton ----

_detector_singleton: MolDetv2Detector | None = None
_detector_lock = threading.Lock()


def get_moldet() -> MolDetv2Detector:
    """Return the global MolDetv2 detector singleton (thread-safe).

    Before first creation, ResourceManager ensures the weights are in place
    (auto-fetched from ModelScope on first run); ``ensure`` is idempotent and
    a fast no-op when the weights already exist.
    """
    global _detector_singleton
    if _detector_singleton is None:
        with _detector_lock:
            if _detector_singleton is None:
                from mbforge.infra.resource_manager import ResourceManager

                ResourceManager.ensure("moldet")
                _detector_singleton = MolDetv2Detector()
    return _detector_singleton


def unload() -> None:
    """Release the process-wide detector model, if it is loaded."""
    global _detector_singleton
    with _detector_lock:
        _detector_singleton = None

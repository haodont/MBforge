"""Hiro-Layout (RT-DETR-X, ONNX) layout-region detection backend.

This module owns model loading, ONNX inference, and the raw region boxes
(``label`` + pixel bbox + score) that the layout pipeline assembles into typed
regions. The label → RegionType / category mapping deliberately lives in the
pipeline layer (``mbforge.pipeline.layout.labels``) so this backend stays a
pure detector.

Three facts carried over from the source project must not be "simplified":

1. The class table comes from the ONNX metadata ``names``, not ``labels.json``.
   The published ``labels.json`` / ``config.json`` use a re-grouped order that
   does **not** match the weight's output indices — reading it turns body text
   into "structure diagram" (411/518 of the ``idx=2`` boxes overlapped V3's
   ``text`` regions on the 256-page sample).
2. The only working input size is a **640x640 letterbox**; deviating degrades
   detection monotonically (and collapses to zero at 1600).
3. ONNX metadata ``license`` says AGPL-3.0 (an ultralytics exporter boilerplate
   string) while the model card says Apache-2.0. Needs PatSnap clarification
   before commercial use — see ``RESOURCE_CATALOG["hiro_layout"]``.

Region boxes are returned in **image pixel coordinates, top-left origin**,
matching :mod:`mbforge.backends.moldet_v2_ft`. The PDF-point conversion happens
in the pipeline layer.
"""

from __future__ import annotations

import ast
import contextlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mbforge.utils.logger import get_logger

logger = get_logger(__name__)

#: Class table from the ONNX metadata ``names``. The ONNX metadata is the
#: authoritative source; this table is the fallback when it cannot be parsed.
HIRO_CLS_TO_LABEL: dict[int, str] = {
    0: "title",
    1: "sec",
    2: "text",
    3: "photo",
    4: "seq",
    5: "head",
    6: "foot",
    7: "draw",
    8: "mnote",
    9: "cap",
    10: "struc",
    11: "figno",
    12: "lineno",
    13: "colno",
    14: "ref",
    15: "toc",
    16: "noise",
    17: "tab",
    18: "eqn",
    19: "chem",
    20: "figcx",
    21: "rxn",
    22: "bib",
    23: "srep",
    24: "graph",
}

#: Letterbox padding value used by the exporter's training pipeline.
LETTERBOX_PAD = 114

#: Default ONNX file, relative to the resolved model directory.
DEFAULT_ONNX_SUBPATH = "layout_model/RT-DETR_25.onnx"

#: ONNX metadata ``imgsz``; the only valid working point.
DEFAULT_IMGSZ = 640


@dataclass
class LayoutBox:
    """One raw region from the layout detector (image pixels, top-left origin)."""

    cls_id: int
    label: str
    bbox_px: tuple[float, float, float, float]
    score: float


def default_model_dir() -> Path:
    """Return the shared model cache directory (unified constant)."""
    from mbforge.utils.paths import get_model_cache_dir

    cache_dir = Path(get_model_cache_dir())
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _has_onnxruntime() -> bool:
    try:
        import onnxruntime  # noqa: F401

        return True
    except ImportError:
        return False


def _preload_gpu_dlls() -> str | None:
    """Preload CUDA / cuDNN runtime DLLs from the ``nvidia-*`` wheels.

    Must run **before** the InferenceSession is created, otherwise the CUDA EP
    silently falls back to CPU — ``session.get_providers()`` is the only honest
    check afterwards (``ort.get_available_providers()`` keeps listing
    CUDAExecutionProvider even when its DLLs failed to load).

    There is a second, subtler hazard: ``preload_dlls()`` puts the ``nvidia``
    cuDNN (CUDA 13) directory on the DLL search path, while ``torch`` ships a
    same-named ``cudnn_cnn64_9.dll`` built for CUDA 12. Windows dedupes by name,
    so loading ``torch`` *after* the preload makes torch pick up the wrong
    build (``OSError WinError 127``). Importing torch first pins its own DLLs.

    Returns ``None`` on success, otherwise a short diagnostic string.
    """
    # Pin torch's DLLs first; best-effort, a pure-ONNX install has no torch.
    with contextlib.suppress(Exception):
        import torch  # noqa: F401

    try:
        import onnxruntime as ort

        preload = getattr(ort, "preload_dlls", None)
        if preload is None:
            return "onnxruntime has no preload_dlls (needs >= 1.21)"
        preload()
        return None
    except Exception as exc:  # noqa: BLE001 — fall back to CPU on any failure
        return f"{type(exc).__name__}: {exc}"


class HiroLayoutDetector:
    """Hiro-Layout (RT-DETR-X, ONNX) region detector.

    ``predict`` returns the raw region boxes for one page image; the caller owns
    page geometry and the label → RegionType mapping.
    """

    def __init__(
        self,
        model_path: Path | None = None,
        *,
        input_size: int | None = DEFAULT_IMGSZ,
        providers: list[str] | None = None,
        num_threads: int | None = None,
    ) -> None:
        if not _has_onnxruntime():
            raise RuntimeError(
                "onnxruntime is not installed; the Hiro-Layout detector cannot "
                "be used. Install it with: uv pip install onnxruntime-gpu"
            )

        import onnxruntime as ort

        self.ort = ort
        self.input_size = input_size
        self.model_path = model_path or self._resolve_model_path()
        self.model: Any | None = None
        self.session = None
        self.input_name = ""
        self.providers: list[str] = []
        self.cls_to_label: dict[int, str] = dict(HIRO_CLS_TO_LABEL)
        self.cls_to_label_source = "hardcoded"
        self.dll_preload_note: str | None = None

        self._load_model(providers=providers, num_threads=num_threads)

    def _resolve_model_path(self) -> Path:
        """Resolve the ONNX weights through ResourceManager."""
        from mbforge.infra.resource_manager import ResourceManager

        resolved = ResourceManager.resolve_model_for_backend(
            "hiro_layout", subpath=DEFAULT_ONNX_SUBPATH
        )
        if resolved is not None and resolved.exists():
            return resolved

        # Fallback: default model directory (matches the catalog local_name).
        return default_model_dir() / "Hiro-Layout" / DEFAULT_ONNX_SUBPATH

    def _load_model(
        self, *, providers: list[str] | None, num_threads: int | None
    ) -> None:
        """Create the ONNX session (missing weights mark the detector unavailable)."""
        if not self.model_path.exists():
            logger.warning(
                "Hiro-Layout model not found: %s (layout detection unavailable)",
                self.model_path,
            )
            return

        logger.info("Loading Hiro-Layout model: %s", self.model_path)
        start = time.perf_counter()

        # Must precede session creation (see _preload_gpu_dlls).
        self.dll_preload_note = _preload_gpu_dlls()

        options = self.ort.SessionOptions()
        options.log_severity_level = 3
        if num_threads:
            options.intra_op_num_threads = num_threads

        if providers is None:
            # Never derive this from ort.get_available_providers(): it lists
            # TensorrtExecutionProvider ahead of CUDA, and TensorRT is absent
            # here, so every session creation logs a failed TRT load first.
            available = set(self.ort.get_available_providers())
            providers = [
                name
                for name in ("CUDAExecutionProvider", "CPUExecutionProvider")
                if name in available
            ] or ["CPUExecutionProvider"]

        session = self.ort.InferenceSession(
            str(self.model_path), options, providers=providers
        )
        self.session = session
        self.providers = list(session.get_providers())
        self.input_name = session.get_inputs()[0].name
        self.model = session

        if "CUDAExecutionProvider" in providers and (
            "CUDAExecutionProvider" not in self.providers
        ):
            logger.warning(
                "Hiro-Layout requested CUDAExecutionProvider but the session "
                "only has %s — silently running on CPU%s",
                self.providers,
                f" (DLL preload: {self.dll_preload_note})"
                if self.dll_preload_note
                else "",
            )

        # ONNX metadata ``names`` is authoritative; labels.json is not usable.
        metadata = dict(session.get_modelmeta().custom_metadata_map)
        self.metadata = metadata
        parsed = self._read_names(metadata)
        if parsed:
            self.cls_to_label = parsed
            self.cls_to_label_source = "onnx-meta"

        logger.info(
            "Hiro-Layout loaded in %.2fs (providers=%s, classes from %s)",
            time.perf_counter() - start,
            self.providers,
            self.cls_to_label_source,
        )

    @staticmethod
    def _read_names(metadata: dict) -> dict[int, str] | None:
        """Parse the ultralytics ``names`` metadata (``"{0: 'title', ...}"``)."""
        raw = metadata.get("names")
        if not raw:
            return None
        try:
            parsed = ast.literal_eval(raw)
            return {int(k): str(v) for k, v in parsed.items()} if parsed else None
        except Exception:  # noqa: BLE001 — malformed metadata falls back
            return None

    @property
    def backend(self) -> str:
        return f"onnxruntime/{self.ort.__version__}"

    def is_available(self) -> bool:
        """Whether the detector is usable (session created)."""
        return self.session is not None

    # ---- forward ----

    def _preprocess(self, image: Any, size: int) -> tuple[np.ndarray, float, int, int]:
        """letterbox → /255 → RGB → CHW float32. Returns (tensor, ratio, left, top)."""
        from PIL import Image

        arr = image if isinstance(image, np.ndarray) else np.asarray(image)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, -1)
        arr = arr[:, :, :3]
        height, width = arr.shape[:2]
        ratio = min(size / height, size / width)
        new_h, new_w = max(1, round(height * ratio)), max(1, round(width * ratio))
        resized = np.asarray(
            Image.fromarray(arr.astype(np.uint8)).resize((new_w, new_h), Image.BILINEAR)
        )
        canvas = np.full((size, size, 3), LETTERBOX_PAD, dtype=np.uint8)
        left, top = (size - new_w) // 2, (size - new_h) // 2
        canvas[top : top + new_h, left : left + new_w] = resized
        tensor = canvas.astype(np.float32) / 255.0
        return tensor.transpose(2, 0, 1)[None], ratio, left, top

    def _decode_page(
        self,
        output: np.ndarray,
        size: int,
        letterbox: tuple[float, int, int],
        page_w: int,
        page_h: int,
        threshold: float,
        nms_iou: float | None,
    ) -> list[LayoutBox]:
        """Decode one sample's ``(300, 4+nc)`` output into boxes.

        Each sample has its own letterbox ratio/margins, so the inverse
        transform is applied per sample.
        """
        ratio, left, top = letterbox
        boxes = output[:, :4]
        scores = output[:, 4:]
        cls_ids = scores.argmax(1)
        conf = scores[np.arange(len(cls_ids)), cls_ids]

        cx, cy, bw, bh = boxes.T
        xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], 1)
        # Inverse letterbox: canvas-normalized → canvas px → page px.
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] * size - left) / ratio
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] * size - top) / ratio

        keep = conf >= threshold
        xyxy, conf, cls_ids = xyxy[keep], conf[keep], cls_ids[keep]

        if nms_iou is not None and len(xyxy):
            selected = _nms(xyxy, conf, nms_iou)
            xyxy, conf, cls_ids = xyxy[selected], conf[selected], cls_ids[selected]

        found: list[LayoutBox] = []
        for box, score, cls_id in zip(xyxy, conf, cls_ids, strict=True):
            cid = int(cls_id)
            bounds = (page_w, page_h, page_w, page_h)
            bounded = tuple(
                round(min(max(float(value), 0.0), limit), 2)
                for value, limit in zip(box, bounds, strict=True)
            )
            found.append(
                LayoutBox(
                    cls_id=cid,
                    label=self.cls_to_label.get(cid, f"unk_{cid}"),
                    bbox_px=bounded,  # type: ignore[arg-type]
                    score=float(score),
                )
            )
        found.sort(key=lambda item: -item.score)
        return found

    def _resolve_size(self, size: int | dict | None) -> int:
        """Accept ``None`` / int / ``{"height","width"}``; Hiro is square-only."""
        if size is None:
            return int(self.input_size or DEFAULT_IMGSZ)
        if isinstance(size, dict):
            return int(
                min(size.get("height", DEFAULT_IMGSZ), size.get("width", DEFAULT_IMGSZ))
            )
        return int(size)

    def predict(
        self,
        image: Any,
        threshold: float = 0.4,
        size: int | dict | None = None,
        nms_iou: float | None = None,
    ) -> list[LayoutBox]:
        """Detect regions on one page image (PIL Image or HWC numpy array)."""
        return self.predict_batch(
            [image], threshold=threshold, size=size, nms_iou=nms_iou
        )[0]

    def predict_batch(
        self,
        images: list[Any],
        threshold: float = 0.4,
        size: int | dict | None = None,
        nms_iou: float | None = None,
    ) -> list[list[LayoutBox]]:
        """Batched forward: N pages stacked into one ``session.run`` call.

        Preprocessing still letterboxes each image individually (ratios and
        margins differ), but the tensor is always ``[N,3,S,S]`` so a single
        forward pass suffices.
        """
        if not self.is_available():
            raise RuntimeError(f"Hiro-Layout model not loaded: {self.model_path}.")
        if not images:
            return []

        resolved = self._resolve_size(size)
        tensors: list[np.ndarray] = []
        letterboxes: list[tuple[float, int, int]] = []
        page_sizes: list[tuple[int, int]] = []
        for image in images:
            if hasattr(image, "shape"):
                page_h, page_w = int(image.shape[0]), int(image.shape[1])
            else:
                page_w, page_h = int(image.width), int(image.height)
            tensor, ratio, left, top = self._preprocess(image, resolved)
            tensors.append(tensor[0])
            letterboxes.append((ratio, left, top))
            page_sizes.append((page_w, page_h))

        batch = np.stack(tensors, 0)
        outputs = self.session.run(None, {self.input_name: batch})[0]

        results = []
        for index in range(len(images)):
            page_w, page_h = page_sizes[index]
            results.append(
                self._decode_page(
                    outputs[index],
                    resolved,
                    letterboxes[index],
                    page_w,
                    page_h,
                    threshold,
                    nms_iou,
                )
            )
        return results


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
    """Class-agnostic greedy NMS (score-descending). ``boxes`` is xyxy."""
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        current = order[0]
        keep.append(int(current))
        if order.size == 1:
            break
        rest = order[1:]
        ix0 = np.maximum(boxes[current, 0], boxes[rest, 0])
        iy0 = np.maximum(boxes[current, 1], boxes[rest, 1])
        ix1 = np.minimum(boxes[current, 2], boxes[rest, 2])
        iy1 = np.minimum(boxes[current, 3], boxes[rest, 3])
        inter = np.clip(ix1 - ix0, 0, None) * np.clip(iy1 - iy0, 0, None)
        area_i = (boxes[current, 2] - boxes[current, 0]) * (
            boxes[current, 3] - boxes[current, 1]
        )
        area_rest = (boxes[rest, 2] - boxes[rest, 0]) * (
            boxes[rest, 3] - boxes[rest, 1]
        )
        iou = inter / np.clip(area_i + area_rest - inter, 1e-9, None)
        order = rest[iou <= iou_threshold]
    return np.array(keep, dtype=int)


# ---- Pipeline boundary (gpu-gated) ----

_process_singleton: HiroLayoutDetector | None = None
_detector_lock = threading.Lock()


def get_hiro() -> HiroLayoutDetector:
    """Return the process-wide detector singleton (thread-safe).

    ``ResourceManager.ensure`` auto-fetches the weights on first use and is a
    fast no-op afterwards.
    """
    global _process_singleton
    if _process_singleton is None:
        with _detector_lock:
            if _process_singleton is None:
                from mbforge.infra.resource_manager import ResourceManager

                ResourceManager.ensure("hiro_layout")
                _process_singleton = HiroLayoutDetector()
    return _process_singleton


def _resolve_detector(
    detector: HiroLayoutDetector | None,
) -> HiroLayoutDetector | None:
    """Return a usable detector or ``None`` (with a warning logged)."""
    if detector is None:
        try:
            detector = get_hiro()
        except (ImportError, RuntimeError, OSError) as exc:
            logger.warning("Hiro-Layout initialization failed: %s", exc)
            return None
    if not isinstance(detector, HiroLayoutDetector):
        logger.warning("Hiro-Layout unavailable, skipping layout detection")
        return None
    if not detector.is_available():
        logger.warning("Hiro-Layout model not loaded, skipping layout detection")
        return None
    return detector


def detect_regions_batch(
    images: list[Any],
    detector: HiroLayoutDetector | None = None,
    *,
    threshold: float = 0.4,
) -> list[list[LayoutBox]]:
    """Detect layout regions for a batch of page images, under the GPU gate.

    Order is preserved 1:1 with the input list. An unavailable model degrades to
    one empty result per image so layout detection never breaks a run.
    """
    if not images:
        return []
    resolved = _resolve_detector(detector)
    if resolved is None:
        return [[] for _ in images]

    from ..infra.process import gpu_gate

    with gpu_gate():
        return resolved.predict_batch(images, threshold=threshold)


def detect_regions(
    image: Any,
    detector: HiroLayoutDetector | None = None,
    *,
    threshold: float = 0.4,
) -> list[LayoutBox]:
    """Detect layout regions on a single page image."""
    return detect_regions_batch([image], detector, threshold=threshold)[0]


def unload() -> None:
    """Release the process-wide detector model, if it is loaded."""
    global _process_singleton
    with _detector_lock:
        _process_singleton = None


__all__ = [
    "DEFAULT_ONNX_SUBPATH",
    "HIRO_CLS_TO_LABEL",
    "HiroLayoutDetector",
    "LayoutBox",
    "detect_regions",
    "detect_regions_batch",
    "get_hiro",
    "unload",
]

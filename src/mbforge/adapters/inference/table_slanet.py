"""SLANet-1M table structure recognition backend (ONNX).

Converts a Hiro-Layout ``table`` region crop into an HTML table:

1. preprocess — BGR/grayscale → resize longest side ≤ 488 → ImageNet
   normalize → pad to 488×488 (mirrors ``ResizeTableImage`` + ``PaddingTableImage``)
2. onnxruntime inference — ``slanet_1m.onnx`` outputs structure-token logits
   ``(1, T, 30)`` plus one ``(1, T, 4)`` xyxy box per token
3. TableLabelDecode — argmax token sequence → HTML skeleton, collecting the
   ``<td …>``-opener boxes as cell boxes (scaled back to the input image)
4. cell text — the local RapidOCR reader (``ocr.page_text.read_text_in_boxes``)
   recognizes each cell box on the original crop
5. assemble — cell text is inserted before each ``</td>``, yielding the final
   HTML table consumed by ``layout.table_html.html_table_to_markdown``

Weights come from ``bdatdo0601/slanet-1m-onnx`` (ONNX re-export of the
trained PaddlePaddle model ``dimtri009/SLANet-1M``, MIT), fetched on first use
via ``ResourceManager.ensure("slanet_table")``. Only onnxruntime is needed —
no paddlepaddle dependency.

Recognition is best-effort enrichment: missing weights or inference errors
yield an empty string and never fail the page.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

import numpy as np

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

#: Table-structure character dictionary (inference.yml ``character_dict``).
#: Index 0 is ``<sos>``, index 1 is ``<eos>`` (inserted by TableLabelDecode).
_CHARACTERS: list[str] = [
    "<thead>",
    "<tr>",
    "<td>",
    "</td>",
    "</tr>",
    "</thead>",
    "<tbody>",
    "</tbody>",
    "<td",
    ' colspan="5"',
    ">",
    ' colspan="2"',
    ' colspan="3"',
    ' rowspan="2"',
    ' colspan="4"',
    ' colspan="6"',
    ' rowspan="3"',
    ' colspan="9"',
    ' colspan="10"',
    ' colspan="7"',
    ' rowspan="4"',
    ' rowspan="5"',
    ' rowspan="9"',
    ' colspan="8"',
    ' rowspan="8"',
    ' rowspan="6"',
    ' rowspan="7"',
    ' rowspan="10"',
]
_STRUCTURE_CHARS: list[str] = ["sos", *_CHARACTERS, "eos"]
# PaddleOCR TableLabelDecode with merge_no_span_structure=True: the bare
# ``<td>`` token is merged into ``<td></td>``, so the character list (and the
# model's 30 logits) line up as: sos, 28 structure tokens (with ``<td></td>``
# replacing ``<td>``), eos.
if "<td></td>" not in _STRUCTURE_CHARS:
    _STRUCTURE_CHARS.insert(len(_STRUCTURE_CHARS) - 1, "<td></td>")
_STRUCTURE_CHARS.remove("<td>")
_EOS_INDEX = _STRUCTURE_CHARS.index("eos")
_SOS_INDEX = 0

#: Tokens that open a cell and therefore carry a cell box in bbox_preds.
_TD_TOKENS = frozenset({"<td>", "<td", "<td></td>"})

#: ONNX input size (inference.yml ``ResizeTableImage.max_len`` /
#: ``PaddingTableImage.size``).
_INPUT_SIZE = 488
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_SESSION: Any = None
_AVAILABLE: bool = False
_ERROR: str = ""
_LOAD_LOCK = threading.Lock()


def _has_onnxruntime() -> bool:
    try:
        import onnxruntime  # noqa: F401

        return True
    except ImportError:
        return False


def load(device: str | None = None) -> None:
    """Lazy-load the SLANet-1M ONNX session (thread-safe)."""
    global _SESSION, _AVAILABLE, _ERROR
    if _SESSION is not None:
        return
    with _LOAD_LOCK:
        if _SESSION is not None:
            return

        logger.info("Loading SLANet-1M table structure recognizer...")
        try:
            from mbforge.adapters.runtime.resource_manager import ResourceManager

            path = ResourceManager.get_slanet_path()
            if path is None:
                logger.info(
                    "SLANet-1M weights missing; auto-downloading "
                    "(HF bdatdo0601/slanet-1m-onnx)..."
                )
                ResourceManager.ensure("slanet_table")
                path = ResourceManager.get_slanet_path()
            if path is None:
                _AVAILABLE = False
                _ERROR = (
                    "SLANet-1M weights not found after auto-download "
                    "(check network). Hiro-Layout table regions stay empty."
                )
                logger.warning(_ERROR)
                return

            onnx_path = path / "slanet_1m.onnx"
            if not onnx_path.is_file():
                _AVAILABLE = False
                _ERROR = f"slanet_1m.onnx missing in {path}"
                logger.warning(_ERROR)
                return

            if not _has_onnxruntime():
                _AVAILABLE = False
                _ERROR = (
                    "onnxruntime is not installed; the SLANet-1M recognizer "
                    "cannot be used."
                )
                logger.warning(_ERROR)
                return

            import onnxruntime as ort

            # Must precede session creation (mirrors hiro_layout._preload_gpu_dlls):
            # without it onnxruntime's CUDA EP silently falls back to CPU.
            # 1. Pin torch's own DLLs first — torch ships a CUDA-12 build of
            #    cudnn_cnn64_9.dll; Windows dedupes by name, so preloading the
            #    nvidia-* CUDA-13 cuDNN first would make torch load the wrong one.
            with contextlib.suppress(Exception):
                import torch  # noqa: F401
            # 2. Let onnxruntime discover the nvidia-* wheel DLL directories
            #    (cuBLAS 13 from ``nvidia-cublas``, cuDNN, …).
            preload = getattr(ort, "preload_dlls", None)
            if preload is not None:
                preload()

            options = ort.SessionOptions()
            options.log_severity_level = 3
            available = set(ort.get_available_providers())
            providers = [
                name
                for name in ("CUDAExecutionProvider", "CPUExecutionProvider")
                if name in available
            ] or ["CPUExecutionProvider"]
            _SESSION = ort.InferenceSession(
                str(onnx_path), options, providers=providers
            )
            _AVAILABLE = True
            logger.info(
                "SLANet-1M loaded (providers=%s)",
                list(_SESSION.get_providers()),
            )
        except Exception as exc:  # noqa: BLE001 — enrichment must degrade
            _ERROR = str(exc)
            _AVAILABLE = False
            logger.error("SLANet-1M load failed: %s", exc, exc_info=True)


def unload() -> None:
    """Release model."""
    global _SESSION, _AVAILABLE, _ERROR
    _SESSION = None
    _AVAILABLE = False
    _ERROR = ""


def health() -> dict[str, str]:
    return {
        "status": "ready" if _AVAILABLE else ("error" if _ERROR else "loading"),
        "error": _ERROR,
    }


def _preprocess(image: np.ndarray) -> tuple[np.ndarray, float]:
    """Return ``(x, ratio)``: batched CHW float32 input and px scale factor."""
    import cv2

    if image.ndim == 2:
        bgr = np.stack([image] * 3, axis=-1)
    else:
        bgr = np.ascontiguousarray(image[:, :, :3][:, :, ::-1])
    height, width = bgr.shape[:2]
    ratio = _INPUT_SIZE / max(height, width)
    rh, rw = int(round(height * ratio)), int(round(width * ratio))
    resized = cv2.resize(bgr, (rw, rh), interpolation=cv2.INTER_LINEAR)
    normalized = (resized.astype(np.float32) / 255.0 - _MEAN) / _STD
    padded = np.zeros((_INPUT_SIZE, _INPUT_SIZE, 3), dtype=np.float32)
    padded[:rh, :rw] = normalized
    return padded.transpose(2, 0, 1)[None].astype(np.float32), ratio


def _decode(
    struct_probs: np.ndarray,
    bbox_preds: np.ndarray,
    height: int,
    width: int,
) -> tuple[list[str], list[np.ndarray]]:
    """Map raw outputs to ``(structure_tokens, cell_boxes_xyxy)``.

    Mirrors PaddleOCR's TableLabelDecode (as re-implemented by rapid_table):

    - token logits are argmaxed; decoding stops at the first ``<eos>``
      (``idx > 0``) and ``<sos>``/``<eos>`` tokens are skipped;
    - every ``<td …>`` opener carries a cell box in ``bbox_preds``, given as
      normalized coordinates — scaled back by the original image size;
    - cell boxes keep their token order (all-zero placeholders are left in
      place; the cell-text step skips them) so box ``i`` always belongs to the
      ``i``-th ``<td …>`` opener.
    """
    structure_idx = struct_probs[0].argmax(axis=-1)
    tokens: list[str] = []
    cell_boxes: list[np.ndarray] = []
    for i, char_idx in enumerate(structure_idx):
        if i > 0 and char_idx == _EOS_INDEX:
            break
        if char_idx in (_SOS_INDEX, _EOS_INDEX):
            continue
        text = _STRUCTURE_CHARS[char_idx]
        if text in _TD_TOKENS:
            box = bbox_preds[0][i].copy()
            box[0::2] *= width
            box[1::2] *= height
            cell_boxes.append(box.astype(np.float32))
        tokens.append(text)
    return tokens, cell_boxes


def _cell_texts(image: np.ndarray, cell_boxes: list[np.ndarray]) -> dict[int, str]:
    """Recognize each cell box on the original crop with local RapidOCR."""
    if not cell_boxes:
        return {}
    height, width = image.shape[:2]
    valid: list[tuple[str, list[float]]] = []
    index_of: dict[str, int] = {}
    for i, box in enumerate(cell_boxes):
        x0, y0, x1, y1 = (float(v) for v in box)
        if x1 <= x0 or y1 <= y0:
            continue
        x0, y0 = max(0.0, x0), max(0.0, y0)
        x1, y1 = min(float(width), x1), min(float(height), y1)
        if x1 <= x0 or y1 <= y0:
            continue
        key = f"slanet-cell-{i}"
        index_of[key] = i
        valid.append((key, [x0, y0, x1, y1]))
    if not valid:
        return {}

    from mbforge.adapters.inference.ocr import page_text

    try:
        recognized = page_text.read_text_in_boxes(image, valid)
    except Exception as exc:  # noqa: BLE001 — enrichment must never raise
        logger.warning("SLANet cell OCR failed: %s", exc)
        return {}
    return {index_of[key]: (text or "").strip() for key, text in recognized.items()}


def _assemble_html(
    tokens: list[str], cell_boxes: list[np.ndarray], texts: dict[int, str]
) -> str:
    """Insert cell text before each ``</td>`` and wrap the HTML skeleton.

    Cell text ``texts[i]`` belongs to the ``i``-th ``<td …>`` opener in token
    order (box order from ``_decode``). A merged ``<td></td>`` token is
    expanded to carry its text.
    """
    parts: list[str] = ["<html><body><table>"]
    cell_index = 0
    for token in tokens:
        if token == "<td></td>":
            parts.append("<td>")
            parts.append(texts.get(cell_index, ""))
            parts.append("</td>")
            cell_index += 1
        elif token == "</td>":
            parts.append(texts.get(cell_index, ""))
            parts.append(token)
            cell_index += 1
        else:
            parts.append(token)
    parts.append("</table></body></html>")
    return "".join(parts)


def predict_table(image: np.ndarray | Any) -> str:
    """Recognize one table-region crop; return an HTML table (or ``""``).

    Never raises: missing weights, malformed crops and inference errors all
    degrade to an empty string.
    """
    if _SESSION is None:
        load()
    if not _AVAILABLE or _SESSION is None:
        return ""

    try:
        if not isinstance(image, np.ndarray):
            import numpy as _np

            image = _np.asarray(image)
        x, _ = _preprocess(image)
        outputs = _SESSION.run(None, {"x": x})
        if len(outputs) < 2:
            logger.warning("SLANet-1M returned %d outputs (expected 2)", len(outputs))
            return ""
        bbox_preds, struct_probs = outputs[:2]
        height, width = image.shape[:2]
        tokens, cell_boxes = _decode(
            struct_probs, bbox_preds, height=height, width=width
        )
        if not tokens:
            return ""
        texts = _cell_texts(image, cell_boxes)
        return _assemble_html(tokens, cell_boxes, texts)
    except Exception as exc:  # noqa: BLE001 — enrichment must never break a run
        logger.warning("SLANet-1M predict failed: %s", exc)
        return ""


__all__ = ["health", "load", "predict_table", "unload"]

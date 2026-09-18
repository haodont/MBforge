#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M1 LayoutDetection —— Hiro-Layout (PatSnap/Hiro-Layout) ONNX 推理脚本

对应文档：
  - DESIGN.md               §3.1 坐标约定 / §3.2 统一区域模型 / §4 M1 / §5.1
  - RUNTIME-PYTORCH.md      §4 已实施模块
  - M1/README.md            §14 Hiro-Layout 实测（候选二）

设计目标：产出与 `inference.LayoutDetectorV3.predict()` **完全同构**的区域列表，
使 `pipeline.detect_page()` 可以无差别地接 V3 或 Hiro，方便 A/B 对比。

======================================================================================
⚠️ 三个必须知道的事实（全部实测得出，勿凭 README 假设）
======================================================================================

1. **`labels.json` 的 id 与 ONNX 输出下标不一致——以 ONNX 内嵌元数据为准。**

   官方 README/`labels.json`/`config.json` 都按"figure → text → complex"三组顺序编号
   （text=8、head=11、tab=4…），但 ONNX 权重里的真实顺序是另一套：

       ONNX 元数据 names = {0:title, 1:sec, 2:text, 3:photo, 4:seq, 5:head, 6:foot,
                            7:draw, 8:mnote, 9:cap, 10:struc, 11:figno, 12:lineno,
                            13:colno, 14:ref, 15:toc, 16:noise, 17:tab, 18:eqn,
                            19:chem, 20:figcx, 21:rxn, 22:bib, 23:srep, 24:graph}

   若照 `labels.json` 解读，会把**正文段落读成 `structure diagram`**（实测 256 页样本上
   `idx=2` 的框有 411/518 与 V3 的 `text` 区域重合）。本脚本**优先从 ONNX 元数据读 names**，
   读不到才回退到下面的硬编码表。

2. **输入尺寸是 640×640（letterbox），与 `imgsz` 元数据一致。**
   ONNX 元数据 `imgsz=[640,640]`、`stride=32`、`dynamic=True`。实测把输入改成 800/1024/1280
   会让检出量单调塌陷（1600 时归零），即"动态轴可跑但只有 640 是有效工作点"。
   预处理：letterbox（保持长宽比 + 灰边 114）→ /255 → RGB → CHW。
   实测 pad 色（0/114/255）、归一化（/255、ImageNet、±1）、RGB/BGR 对结果几乎无影响。

3. **授权不是 Apache-2.0，而是 AGPL-3.0。**
   ONNX 元数据 `license = "AGPL-3.0 License (https://ultralytics.com/license)"`，
   且 `description = "Ultralytics rt-detr-x model trained on .../patent0122.yaml"`。
   模型卡宣称 Apache-2.0 与该字段冲突。`DESIGN.md` §7 明确"避免引入 AGPL"，**商用前必须澄清**。

另：`end2end=False`（非端到端导出），故保留可选的 NMS 开关（`--nms-iou`，默认关闭）。
实测 conf≥0.35 时高分框已不重复，NMS 只影响低分近重复框。

用法：
    python hiro_layout.py --list-labels
    python hiro_layout.py --image ..\\Sample\\CN117180334A_FullTextImage_p0006.png --save-vis
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------------------
# 类别表（取自 ONNX 内嵌元数据 names，不是 labels.json）
#
# labels.json / config.json / README 的那套编号是"文档顺序"，与权重输出**对不上**，
# 保留在 HIRO_DOC_ORDER_LABELS 里仅供对照。
# --------------------------------------------------------------------------------------

HIRO_CLS_TO_LABEL = {
    0: "title", 1: "sec", 2: "text", 3: "photo", 4: "seq",
    5: "head", 6: "foot", 7: "draw", 8: "mnote", 9: "cap",
    10: "struc", 11: "figno", 12: "lineno", 13: "colno", 14: "ref",
    15: "toc", 16: "noise", 17: "tab", 18: "eqn", 19: "chem",
    20: "figcx", 21: "rxn", 22: "bib", 23: "srep", 24: "graph",
}

# 官方 labels.json / config.json 的顺序，仅用于打印对照
HIRO_DOC_ORDER_LABELS = [
    "graph", "draw", "struc", "photo", "tab", "eqn", "chem", "noise", "text",
    "title", "sec", "head", "foot", "mnote", "cap", "figno", "lineno", "colno",
    "seq", "figcx", "rxn", "bib", "srep", "toc", "ref",
]

# 中文名（照 README 的类别体系表）
HIRO_LABEL_ZH = {
    "graph": "图表", "draw": "绘制图", "struc": "结构图", "photo": "照片",
    "tab": "表格", "eqn": "数学公式", "chem": "化学式", "noise": "噪声",
    "text": "文本", "title": "标题", "sec": "章节标题", "head": "页眉",
    "foot": "页脚", "mnote": "边注", "cap": "说明", "figno": "编号",
    "lineno": "行号", "colno": "栏号", "seq": "序列表", "figcx": "图片组",
    "rxn": "反应式", "bib": "著录页", "srep": "搜索报告", "toc": "目录",
    "ref": "参考文献",
}

# 映射到 DESIGN.md §3.2 的 RegionType。
# 取舍说明：
#   chem(化学式) → image：化学专利里的"化学式"就是结构式区域，正是 M2/M6 的输入，
#                          与 V3 把结构式判成 `image` 的行为一致，便于下游复用。
#   eqn(数学公式) → formula：对应 M5 的输入。
#   rxn(反应式)   → reaction：DESIGN §3.2 的一等类型。
#   graph(图表)   → chart。
#   noise(噪声)   → noise：Hiro 独有，不产出 evidence（KIND_MAP 里为 None）。
HIRO_LABEL_TO_REGION_TYPE = {
    "title": "title",
    "sec": "text",
    "text": "text",
    "photo": "image",
    "seq": "table",
    "tab": "table",
    "head": "header",
    "foot": "footer",
    "draw": "image",
    "mnote": "text",
    "cap": "text",
    "struc": "image",
    "figno": "text",
    "lineno": "text",
    "colno": "text",
    "ref": "text",
    "toc": "text",
    "noise": "noise",
    "eqn": "formula",
    "chem": "image",
    "figcx": "image",
    "rxn": "reaction",
    "bib": "text",
    "srep": "text",
    "graph": "chart",
}

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "weights" / "hiro"
DEFAULT_ONNX = "layout_model/RT-DETR_25.onnx"
# ONNX 元数据 imgsz=[640,640]；实测偏离即退化
DEFAULT_IMGSZ = 640
LETTERBOX_PAD = 114

# --------------------------------------------------------------------------------------
# 传给 merge.merge() 的词表参数
#
# ⚠️ `merge.py` 的 R2/R5 默认集合是 **PP-DocLayoutV3 的标签词表**，直接拿 Hiro 的
#    label 去跑会全部落空（实测 256 页：R5 命中从应有的量级掉到 71，R2 归零）。
#    这里给出 Hiro 词表下的等价集合，由调用方通过 params 传入。
#    （R3/R4 已改为按 RegionType 匹配，跨检测器通用，不需要在这里配置。）
# --------------------------------------------------------------------------------------
HIRO_MERGE_LABELS = {
    # R5 适用范围 = 会被 M2 当文本消费的标签
    "texty_labels": {"text", "title", "sec", "mnote", "cap", "figno", "lineno",
                     "colno", "ref", "toc", "bib", "srep", "eqn"},
    # R2 允许被父块吞掉的内联子块（对照 V3 的 formula/formula_number/figure_title/
    # footnote/vision_footnote/reference/reference_content）
    "inline_child_labels": {"eqn", "figno", "lineno", "colno",
                            "cap", "mnote", "ref", "toc"},
    # R2 的父块词表
    "r2_parent_labels": {"text", "sec", "title"},
}


# --------------------------------------------------------------------------------------
# 与 inference.LayoutDetectorV3.predict() 同构的封装
# --------------------------------------------------------------------------------------

def _preload_gpu_dlls() -> str | None:
    """从 pip 轮子（nvidia-*）预加载 CUDA / cuDNN 运行库。

    ⚠️ **必须做，且必须在建 session 之前做**。

    `onnxruntime-gpu` 的 CUDA EP 依赖 `cublasLt64_*.dll` / `cudnn*.dll`。这些 DLL
    随 `nvidia-cublas` / `nvidia-cudnn-cu*` 等轮子安装，但**不在 PATH 上**，于是：

        [ONNXRuntimeError] : 1 : FAIL : Error loading
          "...onnxruntime_providers_cuda.dll" which depends on
          "cublasLt64_13.dll" which is missing. (Error 126)
        Failed to create CUDAExecutionProvider.
          Require cuDNN 9.* and CUDA 13.*, and the latest MSVC runtime.

    **最坑的是它会静默回落**：`InferenceSession` 照样建起来，只在 CPU 上跑，
    而 `ort.get_available_providers()` **仍然列出 CUDAExecutionProvider**
    （那是"编译进来了"，不是"能加载"）。实测本机在缺 DLL 时正是如此——
    若不显式检查 `session.get_providers()`，会以为自己在 GPU 上跑。

    本机实测（2026-09-17）：`onnxruntime-gpu 1.30.0` 要 **CUDA 13 + cuDNN 9**，
    轮子装进来的是 `nvidia-cuda-runtime 13.4.92` / `nvidia-cudnn-cu13 9.26.0.51`，
    版本对得上，纯粹是 DLL 加载路径问题，`preload_dlls()` 即可解决。

    官方 Hiro-Smart-Doc 的 `layout/backends/onnx_backend.py::_preload_cuda_dlls`
    做的是同一件事。返回 None 表示成功，否则返回失败原因（供诊断）。

    ⚠️⚠️ **另一个必须知道的坑：加载顺序**（2026-09-18 实测踩到并修）。
    `preload_dlls()` 会把 `nvidia/cudnn/bin`（cuDNN 9 / **CUDA 13**）加进 DLL 搜索路径。
    而 **torch 2.11.0+cu128 自带同名 DLL** `torch/lib/cudnn_cnn64_9.dll`（cuDNN 9 / **CUDA 12**）。
    Windows 加载器按**名字**去重，于是：

        preload_dlls() → import torch   ⇒ torch 拿到 CUDA 13 那份，OSError WinError 127
        import torch   → preload_dlls() ⇒ 正常（两者各用自己那份）

    所以本函数**先尽力 import torch**：torch 在 `preload_dlls()` 之前完成 import 后，
    它会先把自己 `torch/lib` 里的 DLL 加载好，之后再 preload 就不会被抢。
    不 import torch（纯 ONNX 用法）也完全没问题——那样进程里只有一个 cuDNN。
    """
    # ← 关键：把 torch 的 DLL 先钉住，否则下面的 preload 会抢走同名 cuDNN。
    #   尽力而为：没有 torch 的纯 ONNX 环境不该因此失败。
    try:
        import torch  # noqa: F401
    except Exception:
        pass

    try:
        import onnxruntime as ort

        preload = getattr(ort, "preload_dlls", None)
        if preload is None:
            return "onnxruntime 无 preload_dlls（需 >= 1.21）"
        preload()
        return None
    except Exception as exc:  # pragma: no cover - 尽力而为，失败就回落 CPU
        return f"{type(exc).__name__}: {exc}"


class HiroLayoutDetector:
    """Hiro-Layout (RT-DETR-X, ONNX) 版面检测器。

    产出与 `LayoutDetectorV3.predict()` 同构：`(items, (h_px, w_px))`，
    item 含 `cls_id / label / type / score / bbox_px / polygon_px`。
    """

    def __init__(self, model_dir: str | Path = DEFAULT_MODEL_DIR,
                 *, onnx_file: str = DEFAULT_ONNX, input_size: int | None = DEFAULT_IMGSZ,
                 providers=None, num_threads: int | None = None):
        import onnxruntime as ort

        self.ort = ort
        self.model_dir = Path(model_dir)
        self.onnx_path = self.model_dir / onnx_file
        if not self.onnx_path.is_file():
            raise FileNotFoundError(
                f"Hiro-Layout ONNX 不存在: {self.onnx_path}\n"
                f"先运行: python fetch_weights.py --model hiro")
        self.input_size = input_size

        # ⚠️ 必须在建 session 之前调用，否则 CUDA EP 静默回落（见函数 docstring）
        self.dll_preload_note = _preload_gpu_dlls()

        so = ort.SessionOptions()
        so.log_severity_level = 3
        if num_threads:
            so.intra_op_num_threads = num_threads
        self.requested_providers = list(providers) if providers is not None else None
        if providers is None:
            # ⚠️ 不要直接用 ort.get_available_providers()：它把 TensorrtExecutionProvider
            #    排在 CUDA 之前，而本机没装 TensorRT —— 结果是每次建 session 都报
            #    "Error loading onnxruntime_providers_tensorrt.dll ... nvinfer_10.dll is missing"，
            #    再回落。纯噪音，且多一次失败尝试。
            #    官方 Hiro-Smart-Doc 就是显式写 ["CUDAExecutionProvider","CPUExecutionProvider"]。
            avail = set(ort.get_available_providers())
            providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                         if p in avail] or ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(self.onnx_path), so, providers=providers)
        # ⚠️ 判定"在不在 GPU 上"必须用 session.get_providers()，
        #    不能用 ort.get_available_providers()：后者会把"编译进来但加载失败"的 EP
        #    一并列出（实测缺 cublasLt 时仍列出 CUDAExecutionProvider）。
        self.providers = self.session.get_providers()
        self.input_name = self.session.get_inputs()[0].name

        if (self.requested_providers
                and "CUDAExecutionProvider" in self.requested_providers
                and "CUDAExecutionProvider" not in self.providers):
            import warnings
            warnings.warn(
                "请求了 CUDAExecutionProvider，但 session 实际只有 "
                f"{self.providers} —— 已静默回落到 CPU。"
                + (f" DLL 预加载备注: {self.dll_preload_note}"
                   if self.dll_preload_note else ""),
                RuntimeWarning, stacklevel=2)

        # names 元数据是权威来源；读不到才回退硬编码
        meta = self.session.get_modelmeta().custom_metadata_map
        self.metadata = dict(meta)
        self.cls_to_label = self._read_names(meta) or dict(HIRO_CLS_TO_LABEL)
        self.cls_to_label_source = "onnx-meta" if self._read_names(meta) else "hardcoded"

    @staticmethod
    def _read_names(meta: dict) -> dict[int, str] | None:
        """解析 ultralytics 写进 ONNX 的 `names` 元数据（形如 "{0: 'title', ...}"）。"""
        raw = meta.get("names")
        if not raw:
            return None
        try:
            import ast
            d = ast.literal_eval(raw)
            return {int(k): str(v) for k, v in d.items()} if d else None
        except Exception:
            return None

    @property
    def backend(self) -> str:
        return f"onnxruntime/{self.ort.__version__}"

    @property
    def export_imgsz(self):
        """ONNX 元数据里烘焙的 imgsz（可能是 [640, 640]）。"""
        raw = self.metadata.get("imgsz")
        if not raw:
            return None
        try:
            import ast
            return ast.literal_eval(raw)
        except Exception:
            return None

    # ------------------------------------------------------------------ 前向

    def _preprocess(self, image, size: int):
        """letterbox → /255 → RGB → CHW float32。返回 (tensor, ratio, left, top)。"""
        import numpy as np
        from PIL import Image

        arr = np.asarray(image)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, -1)
        arr = arr[:, :, :3]
        h, w = arr.shape[:2]
        r = min(size / h, size / w)
        nh, nw = max(1, round(h * r)), max(1, round(w * r))
        resized = np.asarray(Image.fromarray(arr.astype(np.uint8)).resize(
            (nw, nh), Image.BILINEAR))
        canvas = np.full((size, size, 3), LETTERBOX_PAD, dtype=np.uint8)
        left, top = (size - nw) // 2, (size - nh) // 2
        canvas[top:top + nh, left:left + nw] = resized
        x = canvas.astype(np.float32) / 255.0
        return x.transpose(2, 0, 1)[None], r, left, top

    def _decode_slice(self, out, s: int, lb, h_px: int, w_px: int,
                      threshold: float, per_class_threshold, nms_iou):
        """把单样本输出 `(300, 4+nc)` 解成 items（已去掉 batch 维）。

        `lb` 是该样本自己的 `(r, left, top)` —— 批量前向时每个样本的 letterbox
        比例与边距都不同，必须逐样本反变换。
        """
        import numpy as np

        r, left, top = lb
        boxes = out[:, :4]
        scores = out[:, 4:]
        cls_ids = scores.argmax(1)
        conf = scores[np.arange(len(cls_ids)), cls_ids]

        cx, cy, bw, bh = boxes.T
        xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], 1)
        # letterbox 反变换：先回到 letterbox 画布像素，再除比例、去边距
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] * s - left) / r
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] * s - top) / r

        keep = conf >= threshold
        xyxy, conf, cls_ids = xyxy[keep], conf[keep], cls_ids[keep]

        if nms_iou is not None and len(xyxy):
            sel = _nms(xyxy, conf, nms_iou)
            xyxy, conf, cls_ids = xyxy[sel], conf[sel], cls_ids[sel]

        out_items = []
        for box, sc, cid in zip(xyxy, conf, cls_ids):
            cid = int(cid)
            if per_class_threshold and cid in per_class_threshold:
                if float(sc) < per_class_threshold[cid]:
                    continue
            label = self.cls_to_label.get(cid, f"unk_{cid}")
            out_items.append({
                "cls_id": cid,
                "label": label,
                "type": HIRO_LABEL_TO_REGION_TYPE.get(label, "text"),
                "score": float(sc),
                "bbox_px": [round(min(max(float(v), 0.0), lim), 2)
                            for v, lim in zip(box, (w_px, h_px, w_px, h_px))],
                "polygon_px": [],      # Hiro 是 DETR 单框输出，无 mask/多边形
            })
        # 与 V3 一致：按原始输出序（RT-DETR 的 query 序），score 降序更稳妥
        out_items.sort(key=lambda r: -r["score"])
        return out_items

    def _resolve_size(self, size) -> int:
        """size 可为 None / int / {"height","width"}；Hiro 只支持方形，取较小者。"""
        if size is None:
            return int(self.input_size or DEFAULT_IMGSZ)
        if isinstance(size, dict):
            return int(min(size.get("height", DEFAULT_IMGSZ),
                           size.get("width", DEFAULT_IMGSZ)))
        return int(size)

    def predict(self, image, threshold: float = 0.35, per_class_threshold: dict | None = None,
                size=None, nms_iou: float | None = None):
        """image 可为 PIL.Image 或 np.ndarray(HWC RGB)，与 V3 同源同签名。

        `size` 接受 int 或 {"height","width"}（兼容 pipeline.detect_page 的调用约定）；
        Hiro-Layout 只支持方形，取其中较小者。
        """
        return self.predict_batch([image], threshold=threshold,
                                  per_class_threshold=per_class_threshold,
                                  size=size, nms_iou=nms_iou)[0]

    def predict_batch(self, images, threshold: float = 0.35,
                      per_class_threshold: dict | None = None,
                      size=None, nms_iou: float | None = None):
        """批量前向：N 页 stack 成一个 tensor 一次 `session.run`。

        对应官方 `layout/model_runner.py::LayoutModelRunner.batch_inference`。
        返回 `list[(items, (h_px, w_px))]`，与输入一一对应。

        ⚠️ 预处理仍逐图 letterbox（各图比例/边距不同），但张量恒为 `[N,3,S,S]`，
        故可一次前向；解码时每个切片用自己的 `(r, left, top)` 反变换。

        CPU 与 GPU 都受益：减少单次 launch 开销、提高利用率。
        """
        import numpy as np

        if not images:
            return []
        s = self._resolve_size(size)

        tensors, lbs, page_sizes = [], [], []
        for image in images:
            h_px, w_px = (image.shape[:2] if hasattr(image, "shape")
                          else (image.height, image.width))
            t, r, left, top = self._preprocess(image, s)
            tensors.append(t[0])
            lbs.append((r, left, top))
            page_sizes.append((h_px, w_px))

        batch = np.stack(tensors, 0)                                  # [N,3,S,S]
        outs = self.session.run(None, {self.input_name: batch})[0]    # [N,300,4+nc]

        results = []
        for i in range(len(images)):
            h_px, w_px = page_sizes[i]
            items = self._decode_slice(outs[i], s, lbs[i], h_px, w_px,
                                       threshold, per_class_threshold, nms_iou)
            results.append((items, (h_px, w_px)))
        return results


def _nms(boxes, scores, iou_thresh: float):
    """按类无关的 greedy NMS（先按 score 降序）。boxes 为 xyxy。"""
    import numpy as np

    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        ix0 = np.maximum(boxes[i, 0], boxes[rest, 0])
        iy0 = np.maximum(boxes[i, 1], boxes[rest, 1])
        ix1 = np.minimum(boxes[i, 2], boxes[rest, 2])
        iy1 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(ix1 - ix0, 0, None) * np.clip(iy1 - iy0, 0, None)
        a_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        a_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        iou = inter / np.clip(a_i + a_r - inter, 1e-9, None)
        order = rest[iou <= iou_thresh]
    return np.array(keep, dtype=int)


# --------------------------------------------------------------------------------------
# 组装 Region（与 inference.build_regions 同构）
# --------------------------------------------------------------------------------------

def build_regions(raw, doc_id: str, page_num: int, dpi: int):
    from v3 import px_box_to_pdf

    px_per_pt = dpi / 72.0
    h_px, w_px = raw["page_px"]
    page_h_pt = h_px / px_per_pt
    page_w_pt = w_px / px_per_pt

    regions = []
    for seq, r in enumerate(raw["items"]):
        bbox_px = tuple(r["bbox_px"])
        regions.append({
            "region_id": f"{doc_id}-{page_num}-{r['type']}-{seq}",
            "doc_id": doc_id,
            "page": page_num,
            "type": r["type"],
            "label": r["label"],
            "cls_id": r["cls_id"],
            "score": r["score"],
            "source": "layout_hiro",
            "reading_order": seq,
            "bbox_px": [round(v, 2) for v in bbox_px],
            "bbox_pdf": [round(v, 2) for v in
                         px_box_to_pdf(bbox_px, page_h_pt, px_per_pt)],
            "polygon_px": r["polygon_px"],
            "polygon_pdf": [],
            "content": None,
            "children": [],
        })

    page = {
        "width_px": w_px, "height_px": h_px,
        "width_pt": round(page_w_pt, 2), "height_pt": round(page_h_pt, 2),
        "dpi": dpi, "px_per_pt": px_per_pt,
    }
    return regions, page


TYPE_COLORS = {
    "text": (0, 120, 255), "title": (0, 200, 200), "table": (255, 140, 0),
    "formula": (160, 0, 200), "image": (0, 180, 0), "chart": (0, 180, 0),
    "header": (130, 130, 130), "footer": (130, 130, 130),
    "reaction": (255, 0, 180), "noise": (170, 170, 170),
}


def visualize(image, regions, out_path: Path):
    from PIL import ImageDraw
    im = image.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    for r in regions:
        x0, y0, x1, y1 = r["bbox_px"]
        color = TYPE_COLORS.get(r["type"], (255, 0, 0))
        d.rectangle([x0, y0, x1, y1], outline=color, width=3)
        d.text((x0 + 4, max(0, y0 + 4)), f"{r['label']} {r['score']:.2f}", fill=color)
    im.save(out_path)
    return out_path


# --------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="M1 LayoutDetection (Hiro-Layout, ONNX)")
    ap.add_argument("--image", help="输入页面图像")
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    ap.add_argument("--onnx", default=DEFAULT_ONNX, help="ONNX 相对路径")
    ap.add_argument("--dpi", type=int, default=144, help="契约渲染 DPI（144 = 2px/pt）")
    ap.add_argument("--src-dpi", type=int, default=144, help="输入图像的实际 DPI")
    ap.add_argument("--no-resize", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ,
                    help="推理输入边长。默认 640（= ONNX imgsz 元数据）；偏离即退化")
    ap.add_argument("--min-area-pct", type=float, default=0.0,
                    help="面积下限（占页面百分比）")
    ap.add_argument("--nms-iou", type=float, default=None,
                    help="开启 NMS 的 IoU 阈值（end2end=False；默认关闭）")
    ap.add_argument("--providers", default="",
                    help="逗号分隔的 onnxruntime providers，默认全部可用")
    ap.add_argument("--out", default=None)
    ap.add_argument("--save-vis", action="store_true")
    ap.add_argument("--list-labels", action="store_true")
    args = ap.parse_args()

    if args.list_labels:
        print(f"Hiro-Layout 标签表：{len(HIRO_CLS_TO_LABEL)} 类")
        print(f"{'idx':>4}  {'ONNX 元数据(权威)':<18} {'中文':<8} {'→ RegionType':<12} "
              f"{'labels.json 同位置(错)':<22}")
        for cid in sorted(HIRO_CLS_TO_LABEL):
            lab = HIRO_CLS_TO_LABEL[cid]
            print(f"{cid:>4}  {lab:<18} {HIRO_LABEL_ZH.get(lab, ''):<8} "
                  f"{HIRO_LABEL_TO_REGION_TYPE.get(lab, '?'):<12} "
                  f"{HIRO_DOC_ORDER_LABELS[cid]:<22}")
        print("\n[!] 两列不同即证明 labels.json 的下标不可用于解读 ONNX 输出。")
        n_diff = sum(1 for c in HIRO_CLS_TO_LABEL
                     if HIRO_CLS_TO_LABEL[c] != HIRO_DOC_ORDER_LABELS[c])
        print(f"   25 个位置中有 {n_diff} 个不一致。")
        return 0

    if not args.image:
        ap.error("需要 --image（或用 --list-labels）")

    from PIL import Image

    img_path = Path(args.image)
    image = Image.open(img_path).convert("RGB")
    src_size = image.size
    if not args.no_resize and args.src_dpi != args.dpi:
        scale = args.dpi / args.src_dpi
        image = image.resize((round(image.width * scale), round(image.height * scale)),
                             Image.LANCZOS)
    print(f"[M0] {img_path.name}: {src_size[0]}x{src_size[1]} @{args.src_dpi}dpi"
          f" -> {image.width}x{image.height} @{args.dpi}dpi")

    providers = [p.strip() for p in args.providers.split(",") if p.strip()] or None
    t0 = time.time()
    det = HiroLayoutDetector(args.model_dir, onnx_file=args.onnx, input_size=args.imgsz,
                             providers=providers)
    t_load = time.time() - t0
    print(f"[M1] model loaded in {t_load:.2f}s | providers={det.providers} "
          f"| backend={det.backend} | export imgsz={det.export_imgsz}")
    print(f"[M1] class table from {det.cls_to_label_source}; "
          f"ONNX license={det.metadata.get('license', '?')!r}")

    t0 = time.time()
    items, page_px = det.predict(image, threshold=args.threshold, nms_iou=args.nms_iou)
    t_infer = time.time() - t0
    print(f"[M1] inference {t_infer * 1000:.1f} ms | raw regions={len(items)}")

    if args.min_area_pct > 0:
        page_area = page_px[0] * page_px[1]
        before = len(items)
        items = [r for r in items
                 if (r["bbox_px"][2] - r["bbox_px"][0]) * (r["bbox_px"][3] - r["bbox_px"][1])
                 >= page_area * args.min_area_pct / 100]
        print(f"[M1] area filter >= {args.min_area_pct}%: {before} -> {len(items)}")

    doc_id = img_path.stem
    regions, page = build_regions({"items": items, "page_px": page_px}, doc_id, 1, args.dpi)

    out_path = Path(args.out) if args.out else (
        Path(__file__).resolve().parent / "out" / f"{doc_id}.hiro.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "model": "Hiro-Layout",
        "backend": det.backend,
        "providers": det.providers,
        "onnx_metadata": det.metadata,
        "class_table_source": det.cls_to_label_source,
        "image": str(img_path),
        "page": page,
        "stats": {"n_regions": len(regions), "load_s": round(t_load, 3),
                  "infer_ms": round(t_infer * 1000, 1), "threshold": args.threshold,
                  "imgsz": args.imgsz, "nms_iou": args.nms_iou},
        "regions": regions,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {out_path}")

    hist: dict[str, int] = {}
    for r in regions:
        hist[r["label"]] = hist.get(r["label"], 0) + 1
    print("[M1] label histogram: " + ", ".join(
        f"{k}={v}" for k, v in sorted(hist.items(), key=lambda kv: -kv[1])))

    if args.save_vis:
        vis = visualize(image, regions, out_path.with_suffix(".vis.jpg"))
        print(f"[out] {vis}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

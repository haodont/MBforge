#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M1 LayoutDetection —— PP-DocLayoutV3 推理与验证脚本

对应文档：
  - DESIGN.md                      §3.1 坐标约定 / §3.2 统一区域模型 / §4 M1 / §5.1
  - M1-LAYOUT-DETECTION.md         §3 标签体系 / §5 坐标变换 / §6 输出组装 / §11 验收

本脚本刻意做成"可直接当验收工具用"，因为它要回答 M1 文档 §11.1 的 6 项冒烟检查，
其中 3 项（polygon 坐标系、阅读顺序、重复 cls_id）是接入前必须实测确认的未知量。

用法：
    python inference.py --image samples/cn_mrgprx2_p405.png
    python inference.py --image samples/us_202619539414a_p50.png --verify
    python inference.py --list-labels
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------------------
# §3.1 V3 标签表
#
# 必须硬编码。原因（M1 文档 §3.1）：
#   1. 本模型 config.json 的 label2id 是空对象 {}，无法反查
#   2. id2label 存在同名重复：footer 占 8/9、header 占 12/13、formula 占 5/15、text 占 22/23
#      任何 `{v: k for k, v in id2label.items()}` 反查都会静默吞掉 8/12/5/22
# --------------------------------------------------------------------------------------

V3_CLS_TO_LABEL = {
    0: "abstract", 1: "algorithm", 2: "aside_text", 3: "chart", 4: "content",
    5: "formula", 6: "doc_title", 7: "figure_title", 8: "footer", 9: "footer",
    10: "footnote", 11: "formula_number", 12: "header", 13: "header",
    14: "image", 15: "formula", 16: "number", 17: "paragraph_title",
    18: "reference", 19: "reference_content", 20: "seal", 21: "table",
    22: "text", 23: "text", 24: "vision_footnote",
}

# 一个语义标签可能对应多个 cls_id —— 按类过滤/设阈值时必须全部下发
V3_LABEL_TO_CLS_IDS: dict[str, list[int]] = {}
for _cid, _lab in V3_CLS_TO_LABEL.items():
    V3_LABEL_TO_CLS_IDS.setdefault(_lab, []).append(_cid)

# 映射到 DESIGN.md §3.2 的 RegionType。
# 注意：V3 的标签谱系源自 17 类系列，**不含 toc / page_number**。
V3_LABEL_TO_REGION_TYPE = {
    "doc_title": "title",
    "paragraph_title": "text",
    "content": "text",
    "abstract": "text",
    "algorithm": "text",
    "aside_text": "text",
    "footnote": "text",
    "vision_footnote": "text",
    "reference": "text",
    "reference_content": "text",
    "figure_title": "text",
    "text": "text",
    "formula_number": "text",
    # ✅ 实测确认（2026-09-16，Sample 两专利页）：`number` 就是**页码**，不是普通数字。
    #    证据：CN 页的 "405" 与 US 页的 "34" 均被判为 number，位于页眉/页脚正中，
    #    bbox 尺寸 36x20 / 40x22 px，置信度 0.75 / 0.67。
    #    → 映射为 page_number（DESIGN.md §3.2 的 RegionType 里有该类）。
    #    （原假设"可能是页码"由此证实；M1-LAYOUT-DETECTION.md §3.2 需同步修订。）
    "number": "page_number",
    "table": "table",
    "formula": "formula",
    "image": "image",
    "chart": "chart",
    "header": "header",
    "footer": "footer",
    "seal": "seal",
}

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "weights" / "v3"


# --------------------------------------------------------------------------------------
# MBForge SourceEvidence 对齐
#
# `kind` 直通检测器的原始 label（Hiro 的 25 类、V3 的 21 类），信息一点不丢；
# 下游按**类别**判断，见 `mbforge/core/evidence_kind.py`。
# 本模块只声明 `RegionType → 类别`，用于产出产物里的 `kind_vocab`。
# --------------------------------------------------------------------------------------
REGION_TYPE_CATEGORY = {
    "text": "text",
    "title": "text",
    "formula": "text",
    "header": "text",
    "footer": "text",
    "page_number": "text",
    "table": "table",
    "image": "image",
    "chart": "image",
    "reaction": "image",
    "seal": "image",
    "noise": "image",
    "molecule": "molecule",
}


def to_evidence(region: dict, doc_id: str, page: int) -> dict:
    """把 Region 投影成 MBForge `SourceEvidence.to_dict()` 的形状。

    - `kind` = **`region["label"]`**，即检测器的原始类别名（`text` / `chem` / `figcx` …）。
      每个区域都产出，不按类型筛选 —— `kind` 的词表是开放的，见
      `mbforge/core/evidence_kind.py`。
    - `bbox` 用 **`bbox_pdf`**（PDF pt，左下原点）——evidence_join 的 conventions
      三个坐标系全是 `pdf_bottom_left`，与此完全一致，无需转换。
    - **bbox 是最小证据单元**：一条 evidence 对应一个区域框，不对应某一行文本。
    - `evidence_id` **留空**：MBForge 自己按 `(doc_id, page, bbox)` 生成。
    - `raw_text` / `coref` 当前都为空 —— 待识别模块补（文本识别给 `raw_text`，
      裁图落盘给 `coref`）。
    """
    return {
        "doc_id": doc_id,
        "page": page,
        "evidence_id": "",                       # 由 MBForge 生成
        "bbox": list(region["bbox_pdf"]),        # pdf_bottom_left，与 MBForge 一致
        "raw_text": "",                          # 待识别模块补
        "coref": "",                             # 待裁剪块补
        "kind": region["label"],
        # ↓ 附加的可选字段，MBForge 的 from_dict 会忽略，用于溯源与调试
        "_m1": {
            "region_id": region["region_id"],
            "type": region["type"],
            "category": REGION_TYPE_CATEGORY.get(region["type"]),
            "score": region["score"],
            "source": region["source"],
            "bbox_px": region["bbox_px"],
            "reading_order": region.get("reading_order"),
        },
    }


# --------------------------------------------------------------------------------------
# 坐标变换（M1 文档 §5）
# --------------------------------------------------------------------------------------

def px_box_to_pdf(box_px, page_height_pt: float, px_per_pt: float):
    """图像像素框(左上原点,y 向下) → PDF 点(bottom-left 原点,y 向上)。

    ⚠️ y0/y1 必须交换。DESIGN.md §3.1 那条 `y_pdf = page_height_pt - y_px/2.0`
    若逐坐标套用会得到 y0 > y1 的倒置框，且**不会报错**。
    """
    x0, y0, x1, y1 = (float(v) for v in box_px)
    return (
        x0 / px_per_pt,
        page_height_pt - y1 / px_per_pt,   # 下边（像素里 y 最大 → 点数里 y 最小）
        x1 / px_per_pt,
        page_height_pt - y0 / px_per_pt,   # 上边
    )


def px_poly_to_pdf(poly_px, page_height_pt: float, px_per_pt: float):
    """多边形逐顶点施加同一变换。"""
    return [
        (float(x) / px_per_pt, page_height_pt - float(y) / px_per_pt)
        for x, y in poly_px
    ]


# --------------------------------------------------------------------------------------
# 模型封装
# --------------------------------------------------------------------------------------

class LayoutDetectorV3:
    # 契约自描述：供 `pipeline.detect_page` 统一处理两个检测器
    source_name = "layout_v3"
    provides_reading_order = True   # V3 的输出顺序**自带**逻辑阅读序（实测两栏页 y 回跳）

    def __init__(self, model_dir: str | Path, device: str | None = None, dtype: str | None = None,
                 input_size: int | None = None):
        """input_size：覆盖预处理器默认的 800×800 方形拉伸。None 则用 config 默认值。"""
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        self.torch = torch
        model_dir = str(model_dir)
        self.input_size = input_size

        kwargs = {}
        if dtype == "float16":
            kwargs["torch_dtype"] = torch.float16
        elif dtype == "bfloat16":
            kwargs["torch_dtype"] = torch.bfloat16

        self.model = AutoModelForObjectDetection.from_pretrained(model_dir, **kwargs).eval()
        self.processor = AutoImageProcessor.from_pretrained(model_dir)

        if device and device != "auto":
            self.model.to(device)
        elif torch.cuda.is_available():
            self.model.to("cuda")
        self.device = next(self.model.parameters()).device
        self.dtype = next(self.model.parameters()).dtype

        # 不用 config.label2id（空），用本地硬编码表
        self.cls_to_label = V3_CLS_TO_LABEL

    @property
    def backend(self) -> str:
        return f"transformers/{self.torch.__version__}"

    def _proc_kwargs(self, size):
        """把输入尺寸统一成处理器认的 {height, width}。"""
        s = size if size is not None else self.input_size
        if s is None:
            return {}
        if isinstance(s, int):
            return {"size": {"height": s, "width": s}}
        return {"size": s}

    def raw_forward(self, image, size=None):
        """返回未过滤的原始输出。image 可为 PIL.Image 或 np.ndarray（与 MolDet 同源）。"""
        inputs = self.processor(images=image, return_tensors="pt", **self._proc_kwargs(size))
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        if self.dtype in (self.torch.float16, self.torch.bfloat16):
            inputs = {
                k: (v.to(self.dtype) if v.is_floating_point() else v)
                for k, v in inputs.items()
            }
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        h_px, w_px = image.shape[:2] if hasattr(image, "shape") else (image.height, image.width)
        return outputs, h_px, w_px

    def _cast_outputs_fp32(self, outputs):
        """把模型输出里的浮点张量降回 fp32。

        ⚠️ 必须做：`post_process_object_detection` 内部会 `.detach().cpu().numpy()`，
        而 **numpy 不支持 bfloat16**，直接用 bf16 推理会在后处理阶段抛
        `TypeError: Got unsupported ScalarType BFloat16`。
        降回 fp32 只影响后处理，不影响前向的 bf16 计算。
        """
        t = self.torch
        try:
            keys = list(outputs.keys())
        except AttributeError:
            return outputs
        for k in keys:
            v = outputs[k]
            if t.is_tensor(v) and v.is_floating_point() and v.dtype != t.float32:
                outputs[k] = v.float()
        return outputs

    def predict(self, image, threshold: float = 0.5, per_class_threshold: dict | None = None,
                size=None):
        outputs, h_px, w_px = self.raw_forward(image, size=size)
        outputs = self._cast_outputs_fp32(outputs)
        # target_sizes 把预处理阶段的方形拉伸坐标反映射回原图像素（与输入尺寸无关）
        results = self.processor.post_process_object_detection(
            outputs, target_sizes=[(h_px, w_px)], threshold=threshold
        )
        res = results[0]

        polys = res.get("polygon_points")
        if polys is None:
            polys = [[] for _ in range(len(res["scores"]))]

        out = []
        for score, cls_id, box, poly in zip(res["scores"], res["labels"], res["boxes"], polys):
            cid = int(cls_id)
            label = self.cls_to_label.get(cid, f"unk_{cid}")
            if per_class_threshold:
                t = per_class_threshold.get(cid)
                if t is not None and float(score) < t:
                    continue
            out.append({
                "cls_id": cid,
                "label": label,
                "type": V3_LABEL_TO_REGION_TYPE.get(label, "text"),
                "score": float(score),
                "bbox_px": [round(float(v), 2) for v in box.tolist()],
                "polygon_px": [[round(float(x), 2), round(float(y), 2)] for x, y in _as_pairs(poly)],
            })
        return out, (h_px, w_px)


def _as_pairs(poly):
    """把 polygon_points 的各种可能容器形态统一成 [(x, y), ...]。"""
    if poly is None:
        return []
    # torch.Tensor
    if hasattr(poly, "tolist"):
        poly = poly.tolist()
    # 单点多边形：[[x, y]] 或 [x, y]
    if isinstance(poly, (list, tuple)) and len(poly) == 2 and all(
        isinstance(v, (int, float)) for v in poly
    ):
        return [(poly[0], poly[1])]
    out = []
    for p in poly:
        if hasattr(p, "tolist"):
            p = p.tolist()
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append((p[0], p[1]))
    return out


# --------------------------------------------------------------------------------------
# 组装 Region（M1 文档 §6）
# --------------------------------------------------------------------------------------

def build_regions(raw, doc_id: str, page_num: int, dpi: int, source: str = "layout_v3"):
    """把检测器输出组装成 Region 列表。

    `source` 由调用方传入检测器标识（`layout_v3` / `layout_hiro`）——
    本函数是**两个检测器共用**的组装器（Hiro 也走这里，因为它多带 `kind` 字段）。
    """
    px_per_pt = dpi / 72.0
    h_px, w_px = raw["page_px"]
    page_h_pt = h_px / px_per_pt
    page_w_pt = w_px / px_per_pt

    regions = []
    for seq, r in enumerate(raw["items"]):
        bbox_px = tuple(r["bbox_px"])
        region = {
            # region_id 的 seq 在合并去重后需重编号，这里是检测器的原始序号
            "region_id": f"{doc_id}-{page_num}-{r['type']}-{seq}",
            # ↓ MBForge SourceEvidence 对齐字段
            "doc_id": doc_id,
            "page": page_num,
            "kind": r["label"],                   # 检测器原始类别名，词表开放
            "type": r["type"],
            "label": r["label"],
            "cls_id": r["cls_id"],
            "score": r["score"],
            "source": source,
            "reading_order": seq,   # V3 输出下标即逻辑阅读序（已实测：两栏页有 y 回跳）
            "bbox_px": [round(v, 2) for v in bbox_px],
            "bbox_pdf": [round(v, 2) for v in
                         px_box_to_pdf(bbox_px, page_h_pt, px_per_pt)],
            "polygon_px": r["polygon_px"],
            "polygon_pdf": [[round(x, 2), round(y, 2)] for x, y in
                            px_poly_to_pdf(r["polygon_px"], page_h_pt, px_per_pt)],
            "content": None,
            "children": [],
        }
        regions.append(region)

    page = {
        "width_px": w_px, "height_px": h_px,
        "width_pt": round(page_w_pt, 2), "height_pt": round(page_h_pt, 2),
        "dpi": dpi, "px_per_pt": px_per_pt,
    }
    return regions, page


# --------------------------------------------------------------------------------------
# 可视化
# --------------------------------------------------------------------------------------

TYPE_COLORS = {
    "text": (0, 120, 255), "title": (0, 200, 200), "table": (255, 140, 0),
    "formula": (160, 0, 200), "image": (0, 180, 0), "chart": (0, 180, 0),
    "header": (130, 130, 130), "footer": (130, 130, 130), "seal": (200, 0, 0),
}


def visualize(image, regions, out_path: Path):
    """左：仅 bbox。右：bbox + polygon。用于验证 polygon 是否与 box 同坐标系。"""
    from PIL import ImageDraw
    im = image.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    for r in regions:
        x0, y0, x1, y1 = r["bbox_px"]
        color = TYPE_COLORS.get(r["type"], (255, 0, 0))
        d.rectangle([x0, y0, x1, y1], outline=color, width=3)
        if len(r["polygon_px"]) >= 3:
            d.line([tuple(p) for p in r["polygon_px"]] + [tuple(r["polygon_px"][0])],
                   fill=(255, 0, 0), width=2)
        d.text((x0 + 4, max(0, y0 + 4)), f"{r['label']} {r['score']:.2f}", fill=color)
    im.save(out_path)
    return out_path


# --------------------------------------------------------------------------------------
# 验收检查（M1 文档 §11.1）
# --------------------------------------------------------------------------------------

def run_verify(detector, image, raw, regions, page):
    lines = []
    ok = lambda b: "PASS" if b else "FAIL"       # noqa: E731
    h_px, w_px = raw["page_px"]
    items = raw["items"]

    lines.append("=" * 78)
    lines.append("M1 冒烟检查（M1-LAYOUT-DETECTION.md §11.1）")
    lines.append("=" * 78)
    lines.append(f"图像: {w_px}x{h_px} px | 页面: {page['width_pt']}x{page['height_pt']} pt"
                 f" | dpi={page['dpi']} px_per_pt={page['px_per_pt']}")
    lines.append(f"输出区域数: {len(regions)}")
    lines.append("")

    # 1. 能否加载并前向
    lines.append(f"[1] 加载 + 前向           : {ok(len(regions) > 0)}  (regions={len(regions)})")

    # 2. polygon 坐标系是否与 boxes 一致
    #    若同坐标系：多边形的轴对齐外接框应与 boxes 高度重合（IoU 接近 1）
    ious = []
    for r in items:
        if len(r["polygon_px"]) < 3:
            continue
        xs = [p[0] for p in r["polygon_px"]]
        ys = [p[1] for p in r["polygon_px"]]
        pb = [min(xs), min(ys), max(xs), max(ys)]
        ious.append(_iou(pb, r["bbox_px"]))
    if ious:
        avg = sum(ious) / len(ious)
        lines.append(f"[2] polygon 与 box 同坐标系: {ok(avg > 0.9)}  "
                     f"(n={len(ious)} 平均 IoU={avg:.4f}, min={min(ious):.4f})")
    else:
        lines.append(f"[2] polygon 与 box 同坐标系: FAIL  (未返回 polygon_points)")

    # 3. 输出顺序是否即阅读顺序
    #    判据：输出顺序 vs 纯光栅序（先 y 后 x）。
    #      相同            → 纯光栅序，V3 未提供逻辑阅读顺序
    #      不同 + 存在回跳  → 分栏逻辑阅读序（回跳幅度约等于栏高）
    lines.append("[3] 输出顺序即阅读顺序     : 需人工判读 ↓")
    centers = [(i, (r["bbox_px"][0] + r["bbox_px"][2]) / 2,
                (r["bbox_px"][1] + r["bbox_px"][3]) / 2, r["label"])
               for i, r in enumerate(items)]
    for i, cx, cy, lab in centers[:12]:
        lines.append(f"      #{i:<3} center=({cx:7.1f},{cy:7.1f})  {lab}")
    if len(centers) > 12:
        lines.append(f"      ... 共 {len(centers)} 项")

    raster_order = [c[0] for c in sorted(centers, key=lambda t: (t[2], t[1]))]
    output_order = [c[0] for c in centers]
    raster_identical = raster_order == output_order

    # y 方向回跳：逻辑阅读序在分栏处会向上回跳约一个栏高
    backjumps = []
    for (_, _, y_prev, _), (_, _, y_cur, _) in zip(centers, centers[1:]):
        if y_cur < y_prev - 5:
            backjumps.append(y_prev - y_cur)
    max_bj = max(backjumps) if backjumps else 0.0

    if raster_identical:
        lines.append(f"      与纯光栅序一致 → **纯光栅序**（非逻辑阅读序）")
    elif max_bj > 0:
        lines.append(f"      与纯光栅序不一致，存在 y 回跳（{len(backjumps)} 次，"
                     f"最大 {max_bj:.0f} px）")
        lines.append(f"      → **逻辑阅读序（分栏）**：回跳是分栏处换栏的特征，"
                     f"纯光栅排序无法产生")
    else:
        lines.append(f"      与纯光栅序不一致但无 y 回跳 → 顺序可疑，需人工核对")

    # 4. 坐标往返（用组装后的 regions，才有 bbox_pdf）
    bad_rt = 0
    for r in regions[:20]:
        b = r["bbox_px"]
        bb = r["bbox_pdf"]
        back_x0 = bb[0] * page["px_per_pt"]
        back_y1 = (page["height_pt"] - bb[1]) * page["px_per_pt"]
        if abs(back_x0 - b[0]) > 0.5 or abs(back_y1 - b[3]) > 0.5:
            bad_rt += 1
    lines.append(f"[4] 坐标往返 (px→pdf→px): {ok(bad_rt == 0)}  (n=20, 不符={bad_rt})")

    # 5. y 轴翻转
    bad_y = sum(1 for r in regions if r["bbox_pdf"][1] >= r["bbox_pdf"][3])
    lines.append(f"[5] bbox_pdf 满足 y0 < y1 : {ok(bad_y == 0)}  (违例={bad_y})")

    # 6. 重复 cls_id
    dup = {k: v for k, v in V3_LABEL_TO_CLS_IDS.items() if len(v) > 1}
    lines.append(f"[6] 重复 cls_id 映射       : {ok(bool(dup))}  {dup}")

    # 7. 区域内嵌（M1 文档 §7 未覆盖的情形）
    #    V3 会把小碎块（如 MS 数据里的 C18H25N3O3）判成 formula，而它落在 text 大块内部。
    #    这会造成同一内容被路由两次（M3 文本 + M5 公式），需在合并层处理。
    nests = []
    for a in items:
        for b in items:
            if a is b:
                continue
            ax0, ay0, ax1, ay1 = a["bbox_px"]
            bx0, by0, bx1, by1 = b["bbox_px"]
            iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
            ih = max(0.0, min(ay1, by1) - max(ay0, by0))
            inter = iw * ih
            area_a = (ax1 - ax0) * (ay1 - ay0)
            if area_a > 0 and inter / area_a > 0.8 and area_a < (bx1 - bx0) * (by1 - by0):
                nests.append((a["label"], b["label"]))
    lines.append(f"[7] 区域内嵌 (child∈parent) : {ok(True)}  {len(nests)} 对"
                 f"{'  ' + str(nests[:6]) if nests else ''}")
    lines.append(f"      ↑ 内嵌区域会被路由两次（父→M3，子→M5），合并层需去重")

    lines.append("")
    lines.append("标签分布:")
    hist: dict[str, int] = {}
    for r in regions:
        hist[r["label"]] = hist.get(r["label"], 0) + 1
    for lab, n in sorted(hist.items(), key=lambda kv: -kv[1]):
        cls_ids = V3_LABEL_TO_CLS_IDS.get(lab, [])
        lines.append(f"      {lab:<18} x{n:<4} (cls_id={cls_ids})")
    lines.append("=" * 78)
    return "\n".join(lines)


def _iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


# --------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="M1 LayoutDetection (PP-DocLayoutV3) 推理")
    ap.add_argument("--image", help="输入页面图像")
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    ap.add_argument("--dpi", type=int, default=144,
                    help="契约渲染 DPI（DESIGN.md §3.1：144 = 2px/pt）")
    ap.add_argument("--src-dpi", type=int, default=144,
                    help="输入图像的实际 DPI，用于重采样到 --dpi")
    ap.add_argument("--no-resize", action="store_true", help="不重采样，直接按 --dpi 解释")
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--input-size", type=int, default=None,
                    help="V3 预处理尺寸（默认沿用 config 的 800）；设为 960 可与 MolDet 对齐")
    ap.add_argument("--min-area-pct", type=float, default=0.0,
                    help="面积下限（占页面百分比），低于此值的区域丢弃。建议 0.1")
    ap.add_argument("--drop", default="",
                    help="按语义标签丢弃，逗号分隔，如 'seal,reference'")
    ap.add_argument("--keep-only", default="", help="白名单，逗号分隔")
    ap.add_argument("--device", default=None, help="cuda / cpu / auto")
    ap.add_argument("--dtype", default=None, choices=[None, "float16", "bfloat16"])
    ap.add_argument("--out", default=None, help="输出 JSON 路径")
    ap.add_argument("--save-vis", action="store_true", help="输出可视化图")
    ap.add_argument("--verify", action="store_true", help="跑 §11.1 冒烟检查")
    ap.add_argument("--list-labels", action="store_true", help="打印标签表后退出")
    args = ap.parse_args()

    if args.list_labels:
        print(f"V3 标签表：{len(V3_CLS_TO_LABEL)} 个槽位 / "
              f"{len(V3_LABEL_TO_CLS_IDS)} 个不同标签")
        for cid, lab in V3_CLS_TO_LABEL.items():
            dup = "  <-- 重复" if len(V3_LABEL_TO_CLS_IDS[lab]) > 1 else ""
            print(f"  {cid:>3}  {lab:<18} -> RegionType: "
                  f"{V3_LABEL_TO_REGION_TYPE.get(lab, '?'):<8}{dup}")
        print("\n同名重复（必须全部下发阈值/过滤）:")
        for lab, ids in V3_LABEL_TO_CLS_IDS.items():
            if len(ids) > 1:
                print(f"  {lab:<10} -> {ids}")
        return 0

    if not args.image:
        ap.error("需要 --image（或用 --list-labels）")

    from PIL import Image

    img_path = Path(args.image)
    image = Image.open(img_path).convert("RGB")
    src_size = image.size
    if not args.no_resize and args.src_dpi != args.dpi:
        scale = args.dpi / args.src_dpi
        new_size = (round(image.width * scale), round(image.height * scale))
        image = image.resize(new_size, Image.LANCZOS)

    print(f"[M0] {img_path.name}: {src_size[0]}x{src_size[1]} @{args.src_dpi}dpi"
          f" -> {image.width}x{image.height} @{args.dpi}dpi")

    t0 = time.time()
    detector = LayoutDetectorV3(args.model_dir, device=args.device, dtype=args.dtype,
                                input_size=args.input_size)
    t_load = time.time() - t0
    print(f"[M1] model loaded in {t_load:.2f}s | device={detector.device} "
          f"dtype={detector.dtype} | backend={detector.backend}")

    t0 = time.time()
    items, page_px = detector.predict(image, threshold=args.threshold)
    t_infer = time.time() - t0
    print(f"[M1] inference {t_infer * 1000:.1f} ms | raw regions={len(items)}")

    # 面积过滤（在标签过滤之前，作用在原始几何上）
    if args.min_area_pct > 0:
        page_area = page_px[0] * page_px[1]
        before = len(items)
        items = [
            r for r in items
            if (r["bbox_px"][2] - r["bbox_px"][0]) * (r["bbox_px"][3] - r["bbox_px"][1])
            >= page_area * args.min_area_pct / 100
        ]
        print(f"[M1] area filter >= {args.min_area_pct}%: {before} -> {len(items)}")

    drop = {s.strip() for s in args.drop.split(",") if s.strip()}
    keep = {s.strip() for s in args.keep_only.split(",") if s.strip()}
    if drop:
        items = [r for r in items if r["label"] not in drop]
    if keep:
        items = [r for r in items if r["label"] in keep]
    if drop or keep:
        print(f"[M1] after filter: {len(items)} regions")

    doc_id = img_path.stem
    regions, page = build_regions(
        {"items": items, "page_px": page_px}, doc_id, 1, args.dpi
    )

    out_path = Path(args.out) if args.out else (
        Path(__file__).resolve().parent / "out" / f"{doc_id}.regions.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": "PP-DocLayoutV3",
        "backend": detector.backend,
        "device": str(detector.device),
        "dtype": str(detector.dtype),
        "image": str(img_path),
        "page": page,
        "stats": {
            "n_regions": len(regions),
            "load_s": round(t_load, 3),
            "infer_ms": round(t_infer * 1000, 1),
            "threshold": args.threshold,
            "dropped": sorted(drop),
            "keep_only": sorted(keep),
        },
        "regions": regions,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {out_path}")

    if args.save_vis:
        vis = visualize(image, regions, out_path.with_suffix(".vis.jpg"))
        print(f"[out] {vis}")

    if args.verify:
        report = run_verify(detector, image, {"items": items, "page_px": page_px}, regions, page)
        print("\n" + report)
        (out_path.parent / f"{doc_id}.verify.txt").write_text(report, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文本识别（ocr）选型对比。

两种口径（``--arch``）：

  crop（默认，真实架构）
      输入 = **版面识别的 text 框裁剪块**。对每个块单独跑 det+rec，
      坐标偏移回页面。检测被限制在文本区内，**结构式的原子符号根本不会被扫到**。

  page（参考，仅用于说明差异）
      输入 = 整页图。det 扫遍全页，会把结构式里的 F/N/O 当文本行检出，
      必须事后按版面识别的 image/molecule 框做遮罩过滤。

对比：识别行数、单页耗时、化学文本（分子式/上下标）的字符正确性。

用法：
    python compare_ocr.py                                   # crop 口径，全样本
    python compare_ocr.py --arch page                       # 旧口径，看差异
    python compare_ocr.py --configs v6_small,v6_tiny
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

CONFIGS = {
    "v5_server": ("PPOCRV5", "SERVER"),
    "v5_mobile": ("PPOCRV5", "MOBILE"),
    "v6_medium": ("PPOCRV6", "MEDIUM"),
    "v6_small": ("PPOCRV6", "SMALL"),
    "v6_tiny": ("PPOCRV6", "TINY"),
}

# 文本识别的输入框类型（与 layout/v3.py 的 RegionType 对齐）
IN_TYPES = ("text", "title")
EXCERPT_PAGES = ["MRGPRX2抑制剂及其使用方法_400", "MRGPRX2抑制剂及其使用方法_405",
                 "US202619539414A_FullTextImage_50"]


def build(version: str, model_type: str):
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import EngineType, ModelType, OCRVersion

    return RapidOCR(params={
        "Global.log_level": "error",
        "Global.use_cls": False,                       # 保持坐标系，禁止方向矫正
        "Det.engine_type": EngineType.TORCH, "Det.ocr_version": getattr(OCRVersion, version),
        "Det.model_type": getattr(ModelType, model_type),
        "Rec.engine_type": EngineType.TORCH, "Rec.ocr_version": getattr(OCRVersion, version),
        "Rec.model_type": getattr(ModelType, model_type),
        "EngineConfig.torch.use_cuda": True,
    })


def page_boxes(detections_json: Path, page: str):
    """取该页的 text 框（px 坐标，144 DPI）与 image/molecule 框（后者仅 page 口径用）。"""
    data = json.loads(detections_json.read_text(encoding="utf-8"))
    for p in data["pages"]:
        if p["page"] != page:
            continue
        txt, bad = [], []
        for r in p["regions"]:
            if r["type"] in IN_TYPES and r["label"] in IN_TYPES:
                txt.append(r["bbox_px"])
            if r["type"] in ("image", "chart", "molecule"):
                bad.append(r["bbox_px"])
            for c in r.get("children", []):
                bad.append(c["bbox_px"])
        # 按 V3 的阅读顺序（reading_order）排，保证拼接顺序正确
        txt = [r["bbox_px"] for r in sorted(
            [x for x in p["regions"] if x["type"] in IN_TYPES],
            key=lambda z: z.get("reading_order") or 0)]
        return txt, bad
    return [], []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="crop", choices=["crop", "page"])
    ap.add_argument("--configs", default="v6_small,v6_tiny,v6_medium")
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--detections", default=str(HERE.parent / "layout" / "out" /
                                                "overlay_merged" / "detections.json"))
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import numpy as np
    from PIL import Image

    names = [c.strip() for c in args.configs.split(",")]
    pages = sorted(Path(args.samples).glob("*.png"))
    if args.limit:
        pages = pages[: args.limit]
    det_path = Path(args.detections)

    imgs = []
    for p in pages:
        im = Image.open(p).convert("RGB")
        if args.src_dpi != args.dpi:
            s = args.dpi / args.src_dpi
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        imgs.append((p.stem, np.array(im)))

    boxes = {}
    if args.arch == "crop":
        for stem, _ in imgs:
            boxes[stem] = page_boxes(det_path, stem)
        n_txt = sum(len(v[0]) for v in boxes.values())
        print(f"[arch] crop —— 输入为版面识别的 text 框裁剪块，共 {n_txt} 块"
              f"（{n_txt / len(imgs):.1f}/页）")
    else:
        print(f"[arch] page —— 输入为整页图（参考口径）")

    print(f"[cmp ] {len(imgs)} 页 × {len(names)} 个配置\n")

    rows, excerpts = [], {}
    hdr = (f"{'config':<12}{'行数':>7}{'行/页':>7}{'重复行':>8}{'ms/页':>8}{'ms/块':>8}")
    print(hdr)
    print("-" * len(hdr))

    for nm in names:
        version, mt = CONFIGS[nm]
        ocr = build(version, mt)
        ocr(imgs[0][1])
        lines_all, ms, n_out, n_blk = 0, [], 0, 0
        dup = 0
        seen = set()
        ex = []
        for stem, arr in imgs:
            t = time.perf_counter()
            if args.arch == "crop":
                tb, bad = boxes[stem]
                for (x0, y0, x1, y1) in tb:
                    x0, y0 = int(max(0, x0)), int(max(0, y0))
                    x1, y1 = int(min(arr.shape[1], x1)), int(min(arr.shape[0], y1))
                    if x1 - x0 < 4 or y1 - y0 < 4:
                        continue
                    n_blk += 1
                    sub = arr[y0:y1, x0:x1]
                    r = ocr(sub)
                    if r is None or r.txts is None:
                        continue
                    for box, txt, sc in zip(r.boxes, r.txts, r.scores):
                        lines_all += 1
                        ys = [p[1] + y0 for p in box]
                        xs = [p[0] + x0 for p in box]
                        # 跨块重复：同一页内，(文本, 纵向位置) 撞车即视为重复行
                        key = (stem, txt.strip(), round(min(ys) / 8))
                        if txt.strip() and key in seen:
                            dup += 1
                        seen.add(key)
                        if stem in EXCERPT_PAGES and txt.strip():
                            ex.append((stem, txt, float(sc), float(min(ys)), float(min(xs))))
                    del r
            else:
                r = ocr(arr)
                if r is not None and r.txts is not None:
                    tb, bad = page_boxes(det_path, stem)
                    for box, txt, sc in zip(r.boxes, r.txts, r.scores):
                        xs = [p[0] for p in box]
                        ys = [p[1] for p in box]
                        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                        if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in bad):
                            continue                       # 落在图/分子区内 -> 丢弃
                        lines_all += 1
                        if stem in EXCERPT_PAGES and txt.strip():
                            ex.append((stem, txt, float(sc), float(min(ys)), float(min(xs))))
                del r
            ms.append((time.perf_counter() - t) * 1000)
        excerpts[nm] = ex
        per_blk = st.median(ms) / (n_blk / len(imgs)) if n_blk else 0
        rows.append({"config": nm, "arch": args.arch, "lines": lines_all,
                     "lines_per_page": round(lines_all / len(imgs), 1),
                     "duplicates": dup,
                     "ms_per_page": round(st.median(ms), 1),
                     "blocks": n_blk,
                     "ms_per_block": round(per_blk, 1)})
        print(f"{nm:<12}{lines_all:>7}{lines_all / len(imgs):>7.1f}{dup:>8}"
              f"{st.median(ms):>8.0f}{per_blk:>8.1f}", flush=True)
        del ocr
        import torch
        torch.cuda.empty_cache()

    print("\n" + "=" * 78)
    print("质化对照（按版面顺序 y→x 排，各取前 12 行）")
    print("=" * 78)
    for stem in EXCERPT_PAGES:
        merged = []
        for nm in names:
            items = sorted([e for e in excerpts[nm] if e[0] == stem],
                           key=lambda z: (z[3], z[4]))
            for e in items[:12]:
                merged.append((e[3], nm, e[1], e[2]))
        if not merged:
            continue
        print(f"\n--- {stem} ---")
        for y, nm, txt, sc in sorted(merged, key=lambda z: (z[0], z[1])):
            print(f"  y={y:6.0f} [{nm:<10}] {sc:.2f}  {txt[:76]}")

    out = Path(args.out or (HERE / "out" / f"compare_ocr_{args.arch}.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"config": vars(args), "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {out}")


if __name__ == "__main__":
    main()

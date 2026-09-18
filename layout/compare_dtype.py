#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V3 精度 × 输入尺寸 对比：bf16 能否抵消 1024 的耗时代价？

X 轴无关，直接列 (dtype, imgsz) 组合，报：检出量、耗时、以及与 fp32@800 的框级一致性。

用法：
    python compare_dtype.py
    python compare_dtype.py --combos fp32:800,bf16:800,bf16:1024
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_COMBOS = [("fp32", 800), ("bf16", 800), ("fp16", 800),
                  ("fp32", 1024), ("bf16", 1024)]


def iou(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combos", default="",
                    help="如 fp32:800,bf16:800；默认 5 组")
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--min-area-pct", type=float, default=0.1)
    ap.add_argument("--match-iou", type=float, default=0.5, help="框级一致性判定阈值")
    ap.add_argument("--out", default=str(HERE / "out" / "compare_dtype"))
    args = ap.parse_args()

    import numpy as np
    from PIL import Image

    from detect_overlay import MODEL_V3
    from v3 import LayoutDetectorV3

    combos = DEFAULT_COMBOS
    if args.combos:
        combos = []
        for c in args.combos.split(","):
            dt, sz = c.split(":")
            combos.append((dt, int(sz)))

    pages = sorted(Path(args.samples).glob("*.png"))
    imgs = []
    for p in pages:
        im = Image.open(p).convert("RGB")
        if args.src_dpi != args.dpi:
            s = args.dpi / args.src_dpi
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        imgs.append((p.stem, np.array(im), im.width * im.height))
    print(f"[cmp] {len(imgs)} 页 × {len(combos)} 组 | conf={args.conf} "
          f"| 面积下限={args.min_area_pct}%")

    dtype_arg = {"fp32": None, "bf16": "bfloat16", "fp16": "float16"}
    results = {}
    hdr = (f"{'dtype':<7}{'imgsz':>7}{'过滤后':>8}{'text':>6}{'table':>6}{'image':>7}"
           f"{'ms':>8}{'对fp32@800一致%':>18}")
    print("\n" + hdr)
    print("-" * len(hdr))

    ref_boxes = None
    for dt, size in combos:
        det = LayoutDetectorV3(MODEL_V3, dtype=dtype_arg[dt])
        sz = {"height": size, "width": size}
        det.predict(imgs[0][1], threshold=args.conf, size=sz)   # 预热

        tot = dict(kept=0, text=0, table=0, image=0)
        ms = []
        boxes_all = []
        for stem, arr, area in imgs:
            t = time.perf_counter()
            try:
                items, _ = det.predict(arr, threshold=args.conf, size=sz)
            except Exception as e:
                print(f"{dt:<7}{size:>7}  运行失败: {type(e).__name__}: {str(e)[:60]}")
                results[(dt, size)] = {"error": str(e)}
                det = None
                break
            ms.append((time.perf_counter() - t) * 1000)
            kept = [r for r in items
                    if (r["bbox_px"][2] - r["bbox_px"][0])
                    * (r["bbox_px"][3] - r["bbox_px"][1]) >= area * args.min_area_pct / 100]
            tot["kept"] += len(kept)
            tot["text"] += sum(1 for r in kept if r["type"] == "text")
            tot["table"] += sum(1 for r in kept if r["type"] == "table")
            tot["image"] += sum(1 for r in kept if r["type"] in ("image", "chart"))
            boxes_all.append([r["bbox_px"] for r in kept])
        if det is None:
            continue

        hit = miss = extra = 0
        if ref_boxes is None:
            ref_boxes = boxes_all
            agree = 100.0
        else:
            for ref, cur in zip(ref_boxes, boxes_all):
                matched = set()
                for rb in ref:
                    best = max(((iou(rb, cb), j) for j, cb in enumerate(cur)), default=(0, -1))
                    if best[0] >= args.match_iou:
                        matched.add(best[1])
                    else:
                        miss += 1
                extra += len(cur) - len(matched)
            denom = sum(len(x) for x in ref_boxes)
            agree = (denom - miss) / denom * 100 if denom else 0
        med = st.median(ms)
        results[(dt, size)] = {"kept": tot["kept"], "text": tot["text"],
                               "table": tot["table"], "image": tot["image"],
                               "ms": round(med, 1), "agree_ref_pct": round(agree, 1),
                               "extra": extra if ref_boxes else 0}
        print(f"{dt:<7}{size:>7}{tot['kept']:>8}{tot['text']:>6}{tot['table']:>6}"
              f"{tot['image']:>7}{med:>8.0f}{agree:>18.1f}")
        del det
        import torch
        torch.cuda.empty_cache()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare_dtype.json").write_text(
        json.dumps({"config": vars(args),
                    "rows": [{"dtype": d, "imgsz": s, **v} for (d, s), v in results.items()]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {out}\\compare_dtype.json")


if __name__ == "__main__":
    main()

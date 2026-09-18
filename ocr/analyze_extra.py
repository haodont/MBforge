#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
查清两件事：
  1. v6_medium 比 v6_small 多检出的行**到底是什么**（位置、尺寸、内容）
  2. OCR 的**输出顺序**是否合理（按 bbox 位置重排后与原始顺序对比）

用法：
    python analyze_extra.py --pages 3
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build(version: str, model_type: str):
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import EngineType, ModelType, OCRVersion

    return RapidOCR(params={
        "Global.log_level": "error",
        "Global.use_cls": False,
        "Det.engine_type": EngineType.TORCH, "Det.ocr_version": getattr(OCRVersion, version),
        "Det.model_type": getattr(ModelType, model_type),
        "Rec.engine_type": EngineType.TORCH, "Rec.ocr_version": getattr(OCRVersion, version),
        "Rec.model_type": getattr(ModelType, model_type),
        "EngineConfig.torch.use_cuda": True,
    })


def run(ocr, arr):
    r = ocr(arr)
    out = []
    if r is None or r.txts is None:
        return out
    for box, txt, sc in zip(r.boxes, r.txts, r.scores):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append({"x0": float(min(xs)), "y0": float(min(ys)),
                    "x1": float(max(xs)), "y1": float(max(ys)),
                    "w": float(max(xs) - min(xs)), "h": float(max(ys) - min(ys)),
                    "text": txt, "score": float(sc)})
    return out


def iou(a, b):
    ix0, iy0 = max(a["x0"], b["x0"]), max(a["y0"], b["y0"])
    ix1, iy1 = min(a["x1"], b["x1"]), min(a["y1"], b["y1"])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    u = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / u if u > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--out", default=str(HERE / "out" / "analyze_extra.json"))
    args = ap.parse_args()

    import numpy as np
    from PIL import Image

    pages = sorted(Path(args.samples).glob("*.png"))[: args.pages]
    imgs = []
    for p in pages:
        im = Image.open(p).convert("RGB")
        if args.src_dpi != args.dpi:
            s = args.dpi / args.src_dpi
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        imgs.append((p.stem, np.array(im)))

    small = build("PPOCRV6", "SMALL")
    medium = build("PPOCRV6", "MEDIUM")
    small(imgs[0][1]); medium(imgs[0][1])

    report = {"pages": []}
    print(f"{'page':<34}{'small行':>8}{'medium行':>9}{'多出':>6}"
          f"{'small高':>9}{'medium高':>10}")
    for stem, arr in imgs:
        a = run(small, arr)
        b = run(medium, arr)
        ha = st.median(x["h"] for x in a) if a else 0
        hb = st.median(x["h"] for x in b) if b else 0
        print(f"{stem[:33]:<34}{len(a):>8}{len(b):>9}{len(b) - len(a):>+6}"
              f"{ha:>9.0f}{hb:>10.0f}")

        # medium 独有：在 small 里找不到 IoU>0.3 对应的行
        only = [y for y in b if not any(iou(x, y) > 0.3 for x in a)]
        for o in only:
            o["n_chars"] = len(o["text"])
        report["pages"].append({
            "page": stem,
            "n_small": len(a), "n_medium": len(b),
            "median_h_small": round(ha, 1), "median_h_medium": round(hb, 1),
            "medium_only": only,
        })

    # ---- 多出来的行长什么样 ----
    print("\n" + "=" * 78)
    print("medium 独有行的尺寸分布（这些就是多出来的）")
    print("=" * 78)
    allonly = [o for p in report["pages"] for o in p["medium_only"]]
    print(f"  总 {len(allonly)} 行")
    if allonly:
        hs = sorted(o["h"] for o in allonly)
        ws = sorted(o["w"] for o in allonly)
        cs = sorted(o["n_chars"] for o in allonly)
        print(f"  高(px)  中位 {st.median(hs):.0f}  最小 {hs[0]:.0f}  最大 {hs[-1]:.0f}")
        print(f"  宽(px)  中位 {st.median(ws):.0f}  最小 {ws[0]:.0f}  最大 {ws[-1]:.0f}")
        print(f"  字符数  中位 {st.median(cs):.0f}  最小 {cs[0]}  最大 {cs[-1]}")
        short = [o for o in allonly if o["n_chars"] <= 3]
        print(f"  ≤3 字符的短碎片: {len(short)}/{len(allonly)} "
              f"({len(short) / len(allonly) * 100:.0f}%)")
        print("\n  抽样 25 条（按高升序，看小的是些什么）:")
        for o in sorted(allonly, key=lambda z: z["h"])[:25]:
            print(f"    h={o['h']:5.0f} w={o['w']:5.0f} [{o['score']:.2f}] {o['text'][:46]!r}")

    # ---- 输出顺序是否合理 ----
    print("\n" + "=" * 78)
    print("输出顺序检查（v6_small，第 1 页）")
    print("=" * 78)
    a = run(small, imgs[0][1])
    by_pos = sorted(a, key=lambda z: (z["y0"], z["x0"]))
    same = [x["text"] for x in a] == [x["text"] for x in by_pos]
    print(f"  原始输出顺序 == 按 (y,x) 排序 ? {same}")
    print("  原始输出前 8 行的 y 坐标:", [round(x["y0"]) for x in a[:8]])
    print("  按 y 排序后前 8 行的 y  :", [round(x["y0"]) for x in by_pos[:8]])
    print("\n  原始顺序前 12 行:")
    for x in a[:12]:
        print(f"    y={x['y0']:6.0f} x={x['x0']:6.0f}  {x['text'][:60]!r}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {out}")


if __name__ == "__main__":
    main()

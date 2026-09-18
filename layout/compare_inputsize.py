#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V3 输入尺寸对比渲染：把不同 `size` 下的检测结果分别画出来，供人工逐张对照。

用途：验证"非方形输入可行但更差"这一结论（见 README §5 / §7）。
MolDet 在所有配置下固定不变（@960 / 960_doc），仅作为参照——品红框表示"这里确实有分子"，
据此可以直观看出 V3 在各输入尺寸下漏掉了哪些区域。

用法：
    python compare_inputsize.py                       # 4 页 M1 样本 × 4 种尺寸
    python compare_inputsize.py --samples ..\\Sample   # 换样本集
    python compare_inputsize.py --only 960x960        # 只跑一种
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (标签, height, width) —— 两个维度都必须是 32 的倍数，否则 FPN concat 会崩
CONFIGS = [
    ("640x640",    640,  640),    # 方形，低分辨率
    ("960x960",    960,  960),    # 方形，当前默认
    ("800x1152",  1152,  800),    # 保宽高比，像素量同 960²
    ("1184x1664", 1664, 1184),    # 保宽高比，接近原尺寸（32 倍数修正）
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--out", default=str(HERE / "out" / "inputsize"))
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--conf", type=float, default=0.7)
    ap.add_argument("--mol-conf", type=float, default=0.7)
    ap.add_argument("--mol-imgsz", type=int, default=960)
    ap.add_argument("--only", default="", help="只跑某一档，如 960x960")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    import numpy as np
    from PIL import Image

    from detect_overlay import MOLDET_WEIGHTS, MODEL_V3, draw_page, get_font
    from v3 import LayoutDetectorV3, build_regions

    pages = sorted(Path(args.samples).glob("*.png"))
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        raise SystemExit(f"没找到页面: {args.samples}")

    cfgs = [c for c in CONFIGS if not args.only or c[0] == args.only]
    if not cfgs:
        raise SystemExit(f"--only {args.only} 不在 {[c[0] for c in CONFIGS]} 中")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    v3 = LayoutDetectorV3(MODEL_V3, device=args.device)

    from ultralytics import YOLO
    mol_model = YOLO(str(MOLDET_WEIGHTS["960_doc"]))

    font = get_font(15)
    print(f"[cmp] {len(pages)} 页 × {len(cfgs)} 种输入尺寸 | conf={args.conf}")
    print(f"[mol] MolDet 固定 {MOLDET_WEIGHTS['960_doc'].name} @imgsz {args.mol_imgsz}\n")

    hdr = f"{'config':<14}{'page':<34}{'V3':>5}{'txt':>5}{'tbl':>5}{'img':>5}{'mol':>5}{'ms':>7}"
    print(hdr)
    print("-" * len(hdr))

    index = []
    for label, h, w in cfgs:
        sub = outdir / label
        sub.mkdir(exist_ok=True)
        for p in pages:
            img = Image.open(p).convert("RGB")
            if args.src_dpi != args.dpi:
                s = args.dpi / args.src_dpi
                img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
            arr = np.array(img)

            t = time.perf_counter()
            items, page_px = v3.predict(arr, threshold=args.conf,
                                        size={"height": h, "width": w})
            ms = (time.perf_counter() - t) * 1000
            regions, page = build_regions({"items": items, "page_px": page_px},
                                          p.stem, 1, args.dpi)

            res = mol_model.predict(source=arr, imgsz=args.mol_imgsz,
                                    conf=args.mol_conf, device=args.device,
                                    verbose=False)[0]
            mols = []
            if res.boxes is not None and len(res.boxes):
                for b in res.boxes:
                    x0, y0, x1, y1 = (float(v) for v in b.xyxy[0].tolist())
                    mols.append({"bbox_px": [x0, y0, x1, y1],
                                 "score": float(b.conf[0])})

            vis = draw_page(img, regions, mols, font, f"{p.stem}  |  V3 input {label}")
            vis.save(sub / f"{p.stem}.jpg", quality=88)

            n_txt = sum(1 for r in regions if r["type"] == "text")
            n_tbl = sum(1 for r in regions if r["type"] == "table")
            n_img = sum(1 for r in regions if r["type"] in ("image", "chart"))
            index.append({"config": label, "page": p.stem, "v3": len(regions),
                          "text": n_txt, "table": n_tbl, "image": n_img,
                          "mol": len(mols), "ms": round(ms, 1)})
            print(f"{label:<14}{p.stem[:33]:<34}{len(regions):>5}{n_txt:>5}{n_tbl:>5}"
                  f"{n_img:>5}{len(mols):>5}{ms:>7.0f}")
        print()

    (outdir / "index.json").write_text(
        json.dumps({"configs": [c[0] for c in cfgs], "rows": index},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[out] {outdir}\\<config>\\<page>.jpg")
    print(f"[out] {outdir}\\index.json")
    print()
    print("对比方式：同一页在不同 config 子目录下的同名 jpg 并排看。")
    print("  绿框=image（仅 bbox）  蓝框=text  橙框=table  品红=MolDet 分子（各配置恒同）")


if __name__ == "__main__":
    main()

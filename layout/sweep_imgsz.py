#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
V3 输入尺寸扫描：找出检出量与耗时之间的最佳平衡点。

X 轴 = V3 输入边长（必须 32 的倍数，否则 FPN concat 会崩）
Y 轴 = 检出数量（全 32 页合计）

用法：
    python sweep_imgsz.py
    python sweep_imgsz.py --sizes 640,800,960,1184
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 全部是 32 的倍数；1200 这种非倍数会直接崩（见 README §7.4）
DEFAULT_SIZES = [512, 576, 640, 704, 768, 800, 832, 896, 960,
                 1024, 1088, 1152, 1184, 1216, 1280]


def plot(rows, n_pages, dpi, conf, outdir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    xs = [r["size"] for r in rows]
    scope = f"全 {n_pages} 页" if n_pages else "全样本"
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.6))

    ax = axes[0]
    ax.plot(xs, [r["kept"] for r in rows], "o-", lw=2, color="#1f77b4", label="区域总数（过滤后）")
    ax.plot(xs, [r["text"] for r in rows], "s--", lw=1.6, color="#2ca02c", label="text")
    ax.plot(xs, [r["image"] for r in rows], "^--", lw=1.6, color="#ff7f0e", label="image/chart")
    peak = max(rows, key=lambda r: r["kept"])
    ax.plot([peak["size"]], [peak["kept"]], "*", ms=18, color="gold",
            markeredgecolor="black", zorder=5, label=f"检出峰值 {peak['size']}")
    ax.axvline(800, color="red", ls=":", lw=2, alpha=.8)
    ax.annotate("选用 800", (800, min(r["kept"] for r in rows)),
                color="red", fontsize=11, ha="center", va="bottom")
    ax.set_xlabel("V3 输入边长 (px)")
    ax.set_ylabel(f"{scope}检出数量")
    ax.set_title("检出数量 vs 输入尺寸")
    ax.grid(alpha=.3)
    ax.legend(fontsize=9)

    ax = axes[1]
    ax.plot(xs, [r["table"] for r in rows], "D-", lw=2, color="#d62728")
    for r in rows:
        ax.annotate(str(r["table"]), (r["size"], r["table"]),
                    textcoords="offset points", xytext=(0, 7), ha="center", fontsize=9)
    ax.set_ylim(min(r["table"] for r in rows) - 0.5, max(r["table"] for r in rows) + 1.2)
    ax.set_xlabel("V3 输入边长 (px)")
    ax.set_ylabel(f"table 检出数（{scope}）")
    ax.set_title("表格检出 vs 输入尺寸（M4 入口，不可丢）")
    ax.grid(alpha=.3)

    ax = axes[2]
    ax.plot(xs, [r["ms"] for r in rows], "o-", lw=2, color="#9467bd")
    ax.axvline(800, color="red", ls=":", lw=2, alpha=.8)
    ax.set_xlabel("V3 输入边长 (px)")
    ax.set_ylabel("V3 单页耗时 (ms, 中位)")
    ax.set_title("耗时 vs 输入尺寸")
    ax.grid(alpha=.3)

    fig.suptitle(f"PP-DocLayoutV3 输入尺寸扫描 —— {n_pages} 页真实化学专利 @{dpi}DPI，conf {conf}",
                 fontsize=13)
    fig.tight_layout()
    outdir.mkdir(parents=True, exist_ok=True)
    png = outdir / "sweep_imgsz.png"
    fig.savefig(png, dpi=140)
    plt.close(fig)
    return png


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="", help="逗号分隔，默认扫 15 档")
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--min-area-pct", type=float, default=0.1)
    ap.add_argument("--out", default=str(HERE / "out" / "sweep_imgsz"))
    ap.add_argument("--plot-only", action="store_true",
                    help="不重跑，直接由已存 JSON 重绘（改图不用等 5 分钟）")
    args = ap.parse_args()

    outdir = Path(args.out)
    if args.plot_only:
        data = json.loads((outdir / "sweep_imgsz.json").read_text(encoding="utf-8"))
        png = plot(data["rows"], data.get("n_pages", 0), args.dpi, args.conf, outdir)
        print(f"[out] {png}（由已存 JSON 重绘，未重跑）")
        return

    from PIL import Image

    from detect_overlay import MODEL_V3
    from v3 import LayoutDetectorV3

    sizes = [int(s) for s in args.sizes.split(",")] if args.sizes else DEFAULT_SIZES
    bad = [s for s in sizes if s % 32]
    if bad:
        raise SystemExit(f"以下尺寸不是 32 的倍数，会崩: {bad}")

    pages = sorted(Path(args.samples).glob("*.png"))
    imgs = []
    for p in pages:
        im = Image.open(p).convert("RGB")
        if args.src_dpi != args.dpi:
            s = args.dpi / args.src_dpi
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        imgs.append((p.stem, im))
    print(f"[sweep] {len(imgs)} 页 × {len(sizes)} 档尺寸 | conf={args.conf} "
          f"| 面积下限={args.min_area_pct}%")

    det = LayoutDetectorV3(MODEL_V3)

    rows = []
    hdr = (f"{'size':>6}{'/32':>5}{'像素':>11}{'区域':>7}{'过滤后':>8}"
           f"{'text':>6}{'table':>6}{'image':>7}{'V3 ms':>8}")
    print("\n" + hdr)
    print("-" * len(hdr))

    for s in sizes:
        size = {"height": s, "width": s}
        det.predict(imgs[0][1], threshold=args.conf, size=size)   # 该 shape 预热
        tot = dict(raw=0, kept=0, text=0, table=0, image=0)
        ms = []
        for name, im in imgs:
            arr_area = im.width * im.height
            t = time.perf_counter()
            items, _ = det.predict(im, threshold=args.conf, size=size)
            ms.append((time.perf_counter() - t) * 1000)
            tot["raw"] += len(items)
            kept = [r for r in items
                    if (r["bbox_px"][2] - r["bbox_px"][0])
                    * (r["bbox_px"][3] - r["bbox_px"][1])
                    >= arr_area * args.min_area_pct / 100]
            tot["kept"] += len(kept)
            tot["text"] += sum(1 for r in kept if r["type"] == "text")
            tot["table"] += sum(1 for r in kept if r["type"] == "table")
            tot["image"] += sum(1 for r in kept if r["type"] in ("image", "chart"))
        med = st.median(ms)
        rows.append({"size": s, "px": s * s, "ms": round(med, 1), **tot})
        print(f"{s:>6}{s // 32:>5}{s * s:>11,}{tot['raw']:>7}{tot['kept']:>8}"
              f"{tot['text']:>6}{tot['table']:>6}{tot['image']:>7}{med:>8.0f}")

    # ---------------- 画图 ----------------
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "sweep_imgsz.json").write_text(
        json.dumps({"config": vars(args), "n_pages": len(imgs), "rows": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    png = plot(rows, len(imgs), args.dpi, args.conf, outdir)
    json_path = outdir / "sweep_imgsz.json"

    # ---------------- 结论 ----------------
    best_kept = max(rows, key=lambda r: (r["kept"], -r["ms"]))
    max_tbl = max(r["table"] for r in rows)
    full_tbl = [r for r in rows if r["table"] == max_tbl]
    eight = next((r for r in rows if r["size"] == 800), None)
    print()
    print(f"检出峰值      : {best_kept['size']}×{best_kept['size']}  "
          f"({best_kept['kept']} 区域, {best_kept['ms']:.0f} ms)")
    print(f"table 饱和({max_tbl})  : 自 {full_tbl[0]['size']} 起（"
          f"{'全部达标' if len(full_tbl) == len(rows) else f'{len(full_tbl)}/{len(rows)} 档达标'}）")
    if eight:
        print(f"800×800       : {eight['kept']} 区域, {eight['table']} table, {eight['ms']:.0f} ms")
    print(f"\n[out] {png}")
    print(f"[out] {json_path}")


if __name__ == "__main__":
    main()

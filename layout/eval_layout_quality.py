#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M1 版面质量评测：用**数字版 PDF 自带的结构信息**做真值，双向算召回与误报。

为什么能这么做：数字版 PDF 里，版面元素本身就是机器可读的——

  * **文本** → `page.get_text()` 的逐行 bbox（不是猜的，是作者排版的真实位置）
  * **图形/结构式** → `page.get_drawings()` 的矢量路径 + `page.get_image_info()` 的位图
    （化学结构式在数字版专利里几乎全是**矢量绘图**，不是位图，所以能拿到精确 bbox）
  * **表格** → 长直线规则（本脚本把它从图形真值里剔除，避免给检测器发假分数）

于是可以对每个检测器算**双向**指标（只用数字版页，扫描件无真值）：

  text_recall    = 被 text 型区域覆盖的真值文本像素 / 全部真值文本像素      （越高越好）
  text_on_fig    = text 型区域落在图形真值上的像素 / 该区域总像素          （越低越好，误报）
  fig_recall     = 被 image 型区域覆盖的真值图形像素 / 全部真值图形像素      （越高越好）
  fig_on_text    = image 型区域落在文本真值上的像素 / 该区域总像素          （越低越好，误报）

用法：
    $PY eval_layout_quality.py --runs baseline_256 hiro_256 --out out/layout_quality.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pymupdf

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "Sample"
PDFDIR = Path(r"C:\Users\10954\Desktop\MRGPRX2\03-patent\file")
DPI = 144
PT2PX = DPI / 72.0

# 文本型 / 图形型 RegionType（两侧检测器经各自映射后在此口径上可比）
TEXT_TYPES = {"text", "title", "formula"}
FIG_TYPES = {"image", "chart"}


# ----------------------------------------------------------------- 真值构建

def _fill(mask, x0, y0, x1, y1, w, h):
    a, b = max(0, int(x0)), max(0, int(y0))
    c, e = min(w, int(np.ceil(x1))), min(h, int(np.ceil(y1)))
    if c > a and e > b:
        mask[b:e, a:c] = True


def text_truth(page, w, h):
    m = np.zeros((h, w), dtype=bool)
    for blk in page.get_text("dict").get("blocks", []):
        if blk.get("type") != 0:
            continue
        for line in blk.get("lines", []):
            x0, y0, x1, y1 = line["bbox"]
            _fill(m, x0 * PT2PX, y0 * PT2PX, x1 * PT2PX, y1 * PT2PX, w, h)
    return m


def figure_truth(page, w, h, text_mask, min_area_px=400.0, text_overlap_max=0.30,
                 max_page_frac=0.50):
    """位图 + 矢量绘图聚类 → 图形真值。

    ⚠️ **必须传入 text_mask 并据此剔除**：数字版 PDF 里文字常常是**矢量化**的
    （字体转轮廓），也有大量下划线/表格框线。不剔除的话，`get_drawings()` 会把
    整页文字都算成"图形"——实测未剔除时图形真值高达 35.9M 像素（占页面 44%），
    导致两个检测器的"图形召回"中位数都被压到 0.000（不是模型差，是真值错）。

    ⚠️ **还要剔除"整页背景图"**：本批所谓"数字版" PDF 多数是
    **扫描图 + 不可见 OCR 文本层**（可检索 PDF），于是 `get_image_info()` 会返回
    **一张覆盖整页的位图**——那是页面本身，不是版面里的"图"。
    实测不过滤时，若干页的图形真值 = 100% 页面面积、只有 1 个聚类，
    把"图形召回"算成了无意义的数字。故丢弃面积 > `max_page_frac` 页面面积的聚类。

    剔除规则：
      1. 长直线（框线/下划线）→ 单独进 rule 掩膜，不算图形；
      2. 聚类被文本真值覆盖 > `text_overlap_max` → 是矢量化的文字，不算图形；
      3. 聚类面积 > `max_page_frac` × 页面面积 → 是整页背景，不算图形。
    """
    boxes: list[tuple[float, float, float, float]] = []
    rules: list[tuple[float, float, float, float]] = []

    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        boxes.append((x0 * PT2PX, y0 * PT2PX, x1 * PT2PX, y1 * PT2PX))

    for d in page.get_drawings():
        x0, y0, x1, y1 = d["rect"]
        bw, bh = (x1 - x0) * PT2PX, (y1 - y0) * PT2PX
        if bw <= 0 or bh <= 0:
            continue
        # 极细长的矩形 = 框线/下划线，不是图形内容
        if min(bw, bh) <= 3.0 and max(bw, bh) >= 60.0:
            rules.append((x0 * PT2PX, y0 * PT2PX, x1 * PT2PX, y1 * PT2PX))
            continue
        boxes.append((x0 * PT2PX, y0 * PT2PX, x1 * PT2PX, y1 * PT2PX))

    # 聚类：用膨胀后的重叠关系做 union-find，把结构式的一堆键/环合成一个区域
    pad = 12.0
    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        ax0, ay0, ax1, ay1 = boxes[i]
        for j in range(i + 1, n):
            bx0, by0, bx1, by1 = boxes[j]
            if (ax0 - pad) < bx1 and (bx0 - pad) < ax1 and \
               (ay0 - pad) < by1 and (by0 - pad) < ay1:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)

    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(boxes[i])

    fig = np.zeros((h, w), dtype=bool)
    rule = np.zeros((h, w), dtype=bool)
    clusters, dropped_text, dropped_bg = [], 0, 0
    page_area = float(w * h)
    for members in groups.values():
        x0 = min(b[0] for b in members)
        y0 = min(b[1] for b in members)
        x1 = max(b[2] for b in members)
        y1 = max(b[3] for b in members)
        bw, bh = x1 - x0, y1 - y0
        if bw * bh < min_area_px:
            continue
        # ← 剔除整页背景图（扫描+OCR文本层的可检索 PDF）
        if bw * bh > max_page_frac * page_area:
            dropped_bg += 1
            continue
        # ← 剔除"矢量化的文字"
        a, b = max(0, int(x0)), max(0, int(y0))
        c, e = min(w, int(np.ceil(x1))), min(h, int(np.ceil(y1)))
        if c > a and e > b:
            box_area = (c - a) * (e - b)
            if box_area > 0 and int(text_mask[b:e, a:c].sum()) / box_area > text_overlap_max:
                dropped_text += 1
                continue
        clusters.append([round(v, 1) for v in (x0, y0, x1, y1)])
        # ⚠️ 只填**聚类内各条路径自己的 bbox**，不填聚类外接框。
        #    外接框对稀疏线描图形几乎是空白（化学结构式就是这种），
        #    填外接框会把大片空白算成"图形真值"，从而系统性低估召回
        #    ——而这个偏差恰好打在结构式上，正是我们最关心的类别。
        for bb in members:
            _fill(fig, bb[0], bb[1], bb[2], bb[3], w, h)
    for r in rules:
        _fill(rule, r[0], r[1], r[2], r[3], w, h)

    return fig, rule, clusters, dropped_text, dropped_bg


# ----------------------------------------------------------------- 检测器掩膜

def region_mask(regions, w, h, types):
    m = np.zeros((h, w), dtype=bool)
    for r in regions:
        if r["type"] not in types:
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in r["bbox_px"])
        _fill(m, x0, y0, x1, y1, w, h)
        for ch in r.get("children", []):
            if ch["type"] in types:
                cx0, cy0, cx1, cy1 = (int(round(v)) for v in ch["bbox_px"])
                _fill(m, cx0, cy0, cx1, cy1, w, h)
    return m


def mol_mask(molecules, w, h):
    """M2 / MolDet 的分子框（detections.json 的 pages[].molecules）。"""
    m = np.zeros((h, w), dtype=bool)
    for mol in molecules or []:
        x0, y0, x1, y1 = (int(round(v)) for v in mol["bbox_px"])
        _fill(m, x0, y0, x1, y1, w, h)
    return m


def ratio(num_mask, den_mask, den_total=None):
    """num 落在 den 上的像素 / den_total（默认 den 的像素数）。"""
    d = den_total if den_total is not None else int(den_mask.sum())
    if d <= 0:
        return None
    return float((num_mask & den_mask).sum()) / d


# -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["baseline_256", "hiro_256"],
                    help="M1/out 下的子目录名")
    ap.add_argument("--names", nargs="+", default=None, help="与 --runs 对应的显示名")
    ap.add_argument("--samples", default=str(SAMPLE))
    ap.add_argument("--out", default=str(HERE / "out" / "layout_quality.json"))
    ap.add_argument("--min-text-px", type=int, default=5000,
                    help="真值文本像素少于此值的页跳过（避免噪声页）")
    ap.add_argument("--min-fig-px", type=int, default=3000)
    ap.add_argument("--list-pages", action="store_true",
                    help="打印逐页明细")
    args = ap.parse_args()

    sample = Path(args.samples)
    manifest = json.loads((sample / "_pdf_samples.json").read_text(encoding="utf-8"))
    by_file = {m["file"]: m for m in manifest["added"]}

    runs, mols = {}, {}
    names = args.names or args.runs
    for tag, name in zip(args.runs, names):
        j = json.loads((HERE / "out" / tag / "detections.json").read_text(encoding="utf-8"))
        runs[name] = {p["page"]: p["regions"] for p in j["pages"]}
        mols[name] = {p["page"]: p.get("molecules", []) for p in j["pages"]}

    rows = []
    for png in sorted(sample.glob("*.png")):
        meta = by_file.get(png.name)
        if not meta:
            continue
        pdf = PDFDIR / meta["pdf"]
        if not pdf.exists():
            continue
        doc = pymupdf.open(str(pdf))
        page = doc[meta["pdf_page"] - 1]
        if len(page.get_text().strip()) < 100:
            doc.close()
            continue

        from PIL import Image
        with Image.open(png) as im:
            w, h = im.size

        gt_text = text_truth(page, w, h)
        gt_fig, gt_rule, clusters, dropped, dropped_bg = figure_truth(
            page, w, h, gt_text)
        doc.close()

        n_text, n_fig = int(gt_text.sum()), int(gt_fig.sum())
        if n_text < args.min_text_px and n_fig < args.min_fig_px:
            continue

        row = {"page": png.name, "gt_text_px": n_text, "gt_fig_px": n_fig,
               "n_fig_clusters": len(clusters),
               "dropped_as_text": dropped, "dropped_as_background": dropped_bg,
               # ⚠️ 有整页背景图 = 该页是"扫描图 + OCR 文本层"的可检索 PDF，
               #    它的"文本真值"其实是 OCR 的输出，不是作者排版的真值。
               #    这类页只适合做**相对**比较，不能当绝对准确率。
               "is_scan_with_textlayer": dropped_bg > 0,
               "fig_area_pct_gt": round(100 * n_fig / (w * h), 2)}
        for name, pages in runs.items():
            regs = pages.get(png.stem, [])
            tm = region_mask(regs, w, h, TEXT_TYPES)
            fm = region_mask(regs, w, h, FIG_TYPES)
            mm = mol_mask(mols[name].get(png.stem, []), w, h)
            fu = fm | mm                      # 版面图区 ∪ M2 分子框
            n_tm, n_fm, n_mm, n_fu = (int(tm.sum()), int(fm.sum()),
                                      int(mm.sum()), int(fu.sum()))
            row[name] = {
                "n_regions": len(regs),
                "n_text_regions": sum(1 for r in regs if r["type"] in TEXT_TYPES),
                "n_fig_regions": sum(1 for r in regs if r["type"] in FIG_TYPES),
                "n_molecules": len(mols[name].get(png.stem, [])),
                "text_recall": round(ratio(tm, gt_text), 4) if n_text >= args.min_text_px else None,
                "text_on_fig": round(ratio(tm, gt_fig, n_tm), 4) if n_tm else None,
                "text_on_rule": round(ratio(tm, gt_rule, n_tm), 4) if n_tm else None,
                # 图形召回分三种口径：版面图区 / 仅 M2 / 二者并集
                "fig_recall": round(ratio(fm, gt_fig), 4) if n_fig >= args.min_fig_px else None,
                "mol_recall": round(ratio(mm, gt_fig), 4) if n_fig >= args.min_fig_px else None,
                "union_recall": round(ratio(fu, gt_fig), 4) if n_fig >= args.min_fig_px else None,
                "fig_on_text": round(ratio(fm, gt_text, n_fm), 4) if n_fm else None,
                "fig_area_pct": round(100 * n_fm / (w * h), 2),
                "mol_area_pct": round(100 * n_mm / (w * h), 2),
            }
        rows.append(row)
        if args.list_pages:
            print(f"  {png.name[:46]:<48} text_gt={n_text:>7} fig_gt={n_fig:>7} "
                  f"clusters={len(clusters):>3}")

    # ---------------- 汇总 ----------------
    def agg(name, key, subset=None):
        src = rows if subset is None else [r for r in rows if subset(r)]
        v = [r[name][key] for r in src if r[name].get(key) is not None]
        if not v:
            return None
        a = np.array(v)
        return {"n": len(a), "mean": round(float(a.mean()), 4),
                "median": round(float(np.median(a)), 4),
                "p10": round(float(np.percentile(a, 10)), 4),
                "min": round(float(a.min()), 4)}

    n_vec = sum(1 for r in rows if not r["is_scan_with_textlayer"])
    n_scan = sum(1 for r in rows if r["is_scan_with_textlayer"])

    print("=" * 104)
    print("M1 版面质量：数字版页双向评测（真值 = PDF 文本层 + 矢量图形）")
    print("=" * 104)
    print(f"评估页数: {len(rows)}   （仅数字版；扫描件无真值）")
    print(f"真值文本像素合计: {sum(r['gt_text_px'] for r in rows):,}")
    print(f"真值图形像素合计: {sum(r['gt_fig_px'] for r in rows):,}  "
          f"（{sum(r['n_fig_clusters'] for r in rows)} 个聚类）")
    n_pages_with_fig = sum(1 for r in rows if r["gt_fig_px"] >= args.min_fig_px)
    print(f"  剔除: {sum(r['dropped_as_text'] for r in rows)} 个聚类（矢量文字）、"
          f"{sum(r['dropped_as_background'] for r in rows)} 个（整页背景图）")
    figpct = [r["fig_area_pct_gt"] for r in rows]
    print(f"真值图形占页面面积: 平均 {np.mean(figpct):.1f}%  中位 {np.median(figpct):.1f}%")
    print(f"有图形的页: {n_pages_with_fig}/{len(rows)}（只有这些页参与图形召回）")
    print()

    metrics = [("text_recall", "正文召回 ↑"), ("text_on_fig", "正文误报(压在图上) ↓"),
               ("fig_recall", "图形召回：仅版面模型 ↑"), ("mol_recall", "图形召回：仅 M2/MolDet ↑"),
               ("union_recall", "图形召回：版面 ∪ M2 ↑"), ("fig_on_text", "图区误报(压在文本上) ↓")]
    for key, label in metrics:
        print(f"—— {label} ——")
        print(f"{'检测器':<12}{'页数':>5}{'平均':>10}{'中位':>10}{'p10':>10}{'最差':>10}")
        for name in runs:
            s = agg(name, key)
            if s:
                print(f"{name:<12}{s['n']:>5}{s['mean']:>10.3f}{s['median']:>10.3f}"
                      f"{s['p10']:>10.3f}{s['min']:>10.3f}")
        print()

    print("—— 正文召回，按真值可信度分层（重要）——")
    print("  真矢量 PDF：文本层是作者排版真值 → 可当绝对准确率")
    print("  扫描+OCR文本层：文本层本身是 OCR 输出 → 只能做相对比较，不能当绝对准确率")
    print(f"{'检测器':<12}{'子集':<26}{'页数':>5}{'平均':>10}{'中位':>10}")
    for name in runs:
        for lbl, sub in (("真矢量 PDF", lambda r: not r["is_scan_with_textlayer"]),
                         ("扫描+OCR文本层", lambda r: r["is_scan_with_textlayer"])):
            s = agg(name, "text_recall", subset=sub)
            if s:
                print(f"{name:<12}{lbl:<26}{s['n']:>5}{s['mean']:>10.3f}{s['median']:>10.3f}")
    print()

    # ---------------- 汇总 JSON ----------------
    summary = {"n_pages": len(rows),
               "n_true_vector_pdf": n_vec,
               "n_scan_with_textlayer": n_scan,
               "gt_text_px": sum(r["gt_text_px"] for r in rows),
               "gt_fig_px": sum(r["gt_fig_px"] for r in rows),
               "metrics": {k: {n: agg(n, k) for n in runs} for k, _ in metrics},
               "pages": rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()

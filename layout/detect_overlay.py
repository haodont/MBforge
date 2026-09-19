#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M1 ∪ M2 检测叠加输出（只出 bbox，不做文字识别）

职责（按约定）：
  - **M1 / PP-DocLayoutV3**：出 text 框、table 框，以及其它类型的框
  - **image / chart**：**不主动识别**，仅输出 bbox 四元组
  - **M2 / MolDetv2-YOLO26**：出 molecule 框
  - 不做任何 OCR / 表格结构还原 / 分子结构识别

两者跑在**同一张 144 DPI 页面图**上，坐标天然同构（DESIGN.md §3.1）。

用法：
    python detect_overlay.py                       # 全部 Sample
    python detect_overlay.py --limit 4
    python detect_overlay.py --no-moldet           # 只看 V3
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pipeline import (
    MODEL_V3, MOLDET_WEIGHTS, detect_page, load_hiro, load_moldet, load_v3,
    merge_page, page_image, to_evidence_page,
)

HERE = Path(__file__).resolve().parent
MOLDET = MOLDET_WEIGHTS["960_doc"]

# 配色（按 DESIGN.md §3.2 的 RegionType 分组）
STYLE = {
    "text":         ((0, 102, 255), 2, "text"),
    "table":        ((255, 140, 0), 3, "table"),
    "image":        ((0, 170, 0), 2, "image (bbox only)"),
    "chart":        ((0, 170, 0), 2, "chart (bbox only)"),
    "header":       ((130, 130, 130), 1, "header"),
    "footer":       ((130, 130, 130), 1, "footer"),
    "page_number":  ((130, 130, 130), 1, "page_number"),
    "title":        ((0, 200, 200), 2, "title"),
    "formula":      ((160, 0, 200), 2, "formula"),
    "seal":         ((200, 0, 0), 2, "seal"),
}
MOL_COLOR = (255, 0, 180)


def get_font(size=15):
    from PIL import ImageFont
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_page(img, v3_regions, mols, font, page_title):
    from PIL import ImageDraw
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)

    for r in v3_regions:
        x0, y0, x1, y1 = r["bbox_px"]
        color, w, name = STYLE.get(r["type"], ((255, 0, 0), 2, r["type"]))
        d.rectangle([x0, y0, x1, y1], outline=color, width=w)
        d.text((x0 + 3, max(0, y0 - 17)), f"{name} {r['score']:.2f}",
               fill=color, font=font)

    for i, m in enumerate(mols):
        x0, y0, x1, y1 = m["bbox_px"]
        d.rectangle([x0, y0, x1, y1], outline=MOL_COLOR, width=3)
        d.text((x0 + 3, y1 + 2), f"mol {m['score']:.2f}", fill=MOL_COLOR, font=font)

    # 图例
    legend = [
        (f"V3 total {len(v3_regions)}", (0, 0, 0)),
        (f"  text {sum(1 for r in v3_regions if r['type'] == 'text')}", STYLE["text"][0]),
        (f"  table {sum(1 for r in v3_regions if r['type'] == 'table')}", STYLE["table"][0]),
        (f"  image/chart {sum(1 for r in v3_regions if r['type'] in ('image', 'chart'))}",
         STYLE["image"][0]),
        (f"MolDet molecules {len(mols)}", MOL_COLOR),
    ]
    lh = 20
    lw = 250
    d.rectangle([6, 6, 6 + lw, 6 + lh * len(legend) + 8], fill=(255, 255, 255),
                outline=(0, 0, 0))
    for k, (txt, col) in enumerate(legend):
        d.text((12, 10 + k * lh), txt, fill=col, font=font)
    d.text((12, 10 + (len(legend) + 1) * lh), page_title[:30], fill=(0, 0, 0), font=font)
    return im


def _dashed(d, box, color, width=2, dash=8):
    x0, y0, x1, y1 = box
    for x in range(int(x0), int(x1), dash * 2):
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        d.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width)
    for y in range(int(y0), int(y1), dash * 2):
        d.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width)
        d.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width)


def draw_page_merged(img, regions, font, page_title, mstats):
    """渲染合并后的区域：被抑制的 span 不再出现，容器展开绘制其分子子节点。"""
    from PIL import ImageDraw
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)

    n_kids = 0
    for r in regions:
        x0, y0, x1, y1 = r["bbox_px"]
        meta = r.get("meta") or {}

        # 1:N 容器 —— 虚线框 + 内部分子
        if meta.get("container"):
            _dashed(d, [x0, y0, x1, y1], (0, 120, 0), 3)
            d.text((x0 + 3, max(0, y0 - 17)),
                   f"figure container [{meta.get('molecule_count', 0)} mol]",
                   fill=(0, 120, 0), font=font)
            for c in r["children"]:
                cx0, cy0, cx1, cy1 = c["bbox_px"]
                d.rectangle([cx0, cy0, cx1, cy1], outline=MOL_COLOR, width=3)
                cs = c.get("reading_order")
                d.text((cx0 + 3, cy1 + 2),
                       (f"#{cs} " if cs is not None else "") + f"mol {c['score']:.2f}",
                       fill=MOL_COLOR, font=font)
                n_kids += 1
            continue

        # 分子（独立的 / 由 image 让位来的）
        if r["type"] == "molecule":
            d.rectangle([x0, y0, x1, y1], outline=MOL_COLOR, width=3)
            seq = r.get("reading_order")
            tag = (f"#{seq} " if seq is not None else "") + f"molecule {r['score']:.2f}"
            if r["source"] == "merged":
                tag += " [yielded]"
            d.text((x0 + 3, y1 + 2), tag, fill=MOL_COLOR, font=font)
            continue

        color, w, name = STYLE.get(r["type"], ((255, 0, 0), 2, r["type"]))
        d.rectangle([x0, y0, x1, y1], outline=color, width=w)
        ns = len(meta.get("spans", []))
        # 序号 = reading_order，用来**用眼验证阅读顺序**（框上数字应自上而下、先左栏后右栏）
        seq = r.get("reading_order")
        tag = (f"#{seq} " if seq is not None else "") + f"{name} {r['score']:.2f}" \
              + (f" +{ns}span" if ns else "")
        d.text((x0 + 3, max(0, y0 - 17)), tag, fill=color, font=font)

    # 阅读顺序连通线：按 reading_order 把相邻区域中心连起来，顺带暴露"回跳"
    ordered = [r for r in regions if r.get("reading_order") is not None]
    ordered.sort(key=lambda r: r["reading_order"])
    if len(ordered) > 1:
        pts = [((r["bbox_px"][0] + r["bbox_px"][2]) / 2,
                (r["bbox_px"][1] + r["bbox_px"][3]) / 2) for r in ordered]
        for a, b in zip(pts, pts[1:]):
            d.line([a, b], fill=(160, 160, 160), width=1)
        for i, pt in enumerate(pts):
            d.ellipse([pt[0] - 3, pt[1] - 3, pt[0] + 3, pt[1] + 3],
                      fill=(255, 60, 60) if i else (60, 60, 255))

    legend = [
        (f"merged regions {len(regions)}", (0, 0, 0)),
        (f"  text {sum(1 for r in regions if r['type'] == 'text')}", STYLE["text"][0]),
        (f"  table {sum(1 for r in regions if r['type'] == 'table')}", STYLE["table"][0]),
        (f"  image/chart {sum(1 for r in regions if r['type'] in ('image', 'chart'))}",
         STYLE["image"][0]),
        (f"  molecule {sum(1 for r in regions if r['type'] == 'molecule')}"
         f" (+{n_kids} in containers)", MOL_COLOR),
        (f"R1 dup -{mstats['r1_dup_removed']}  R2 span -{mstats['r2_suppressed']}", (90, 90, 90)),
        (f"R3 yielded {mstats['r3_yielded']}  R4 container {mstats['r4_containers']}", (90, 90, 90)),
    ]
    lh, lw = 20, 300
    d.rectangle([6, 6, 6 + lw, 6 + lh * len(legend) + 8], fill=(255, 255, 255),
                outline=(0, 0, 0))
    for k, (txt, col) in enumerate(legend):
        d.text((12, 10 + k * lh), txt, fill=col, font=font)
    d.text((12, 10 + (len(legend) + 1) * lh), page_title[:32], fill=(0, 0, 0), font=font)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--out", default=str(HERE / "out" / "overlay"))
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144,
                    help="输入图像的实际 DPI；Sample/ 是 144")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--layout", default="v3", choices=["v3", "hiro"],
                    help="版面检测器：v3 = PP-DocLayoutV3(transformers)，"
                         "hiro = Hiro-Layout(ONNX/onnxruntime)")
    ap.add_argument("--conf", type=float, default=0.4, help="版面检测置信度阈值")
    ap.add_argument("--mol-conf", type=float, default=0.4, help="MolDet 置信度阈值")
    ap.add_argument("--imgsz", type=int, default=None,
                    help="版面检测输入尺寸。默认按 --layout 取：v3=800（原生方形）、"
                         "hiro=640（= ONNX imgsz 元数据）。两者偏离原生尺寸都会退化")
    ap.add_argument("--nms-iou", type=float, default=None,
                    help="仅 hiro：开启 NMS 的 IoU 阈值（end2end=False；默认关闭）")
    ap.add_argument("--mol-weights", default="960_doc",
                    help="MolDet 权重：960_doc / 640_general，或直接给 .pt 路径")
    ap.add_argument("--mol-imgsz", type=int, default=960,
                    help="MolDet 推理输入尺寸。默认 960（与 960_doc 权重配套）")
    ap.add_argument("--min-area-pct", type=float, default=0.1,
                    help="V3 区域面积下限（占页面百分比）。分子框天然小，不受此限；设 0 关闭")
    ap.add_argument("--no-moldet", action="store_true")
    ap.add_argument("--merge", action="store_true",
                    help="执行 §7/§7.1 合并：同类去重 + 内嵌抑制 + 1:1让位 + 1:N容器")
    ap.add_argument("--dtype", default="bfloat16",
                    choices=["float32", "bfloat16", "float16"],
                    help="V3 推理精度，默认 bfloat16（显存显著降低）")
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    from v3 import REGION_TYPE_CATEGORY

    pages = sorted(Path(args.samples).glob("*.png"))
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        raise SystemExit(f"没找到页面: {args.samples}")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    imgsz = args.imgsz or (800 if args.layout == "v3" else 640)

    # merge.py 的 R2/R5 词表默认是 V3 的；Hiro 用自己的一套
    merge_params = {}
    if args.layout == "hiro":
        from hiro import HIRO_MERGE_LABELS
        merge_params = {k: set(v) for k, v in HIRO_MERGE_LABELS.items()}

    t0 = time.perf_counter()
    if args.layout == "hiro":
        v3 = load_hiro(input_size=imgsz)
    else:
        v3 = load_v3(MODEL_V3, device=args.device, dtype=args.dtype)
    v3_load = time.perf_counter() - t0

    mol_path = MOLDET_WEIGHTS.get(args.mol_weights, Path(args.mol_weights))
    mol_imgsz = args.mol_imgsz
    mol_model = None
    mol_load = 0.0
    if not args.no_moldet:
        if not mol_path.exists():
            raise SystemExit(f"MolDet 权重不存在: {mol_path}")
        t0 = time.perf_counter()
        mol_model = load_moldet(mol_path)
        mol_load = time.perf_counter() - t0

    font = get_font(15)
    print(f"[det] {len(pages)} 页 | layout={args.layout} | conf 版面={args.conf} "
          f"/ MolDet={args.mol_conf} | 面积下限={args.min_area_pct}%")
    print(f"[{args.layout:<4}] imgsz={imgsz}"
          + ("（原生方形）dtype=" + str(args.dtype) if args.layout == "v3"
             else f"（= ONNX imgsz 元数据）nms_iou={args.nms_iou}")
          + " | 两者共用同一张输入图")
    print(f"[mol] weights={mol_path.name} | imgsz={mol_imgsz}")
    print(f"[load] 版面 {type(v3).__name__}（source={getattr(v3, 'source_name', '?')}，"
          f"自带阅读顺序={getattr(v3, 'provides_reading_order', '?')}）"
          f"{v3_load:.2f}s | MolDet {mol_load:.2f}s\n")

    hdr = (f"{'page':<30}{'lay':>5}{'txt':>5}{'tbl':>5}{'img':>5}{'mol':>5}"
           f"{'merged':>8}{'lay_ms':>8}{'Molms':>8}")
    print(hdr)
    print("-" * len(hdr))

    all_rows = []
    tot = {"v3": 0, "txt": 0, "tbl": 0, "img": 0, "mol": 0, "v3ms": 0.0, "molms": 0.0}
    mtot: dict[str, int] = {}
    n_area_dropped = 0
    evidence: list[dict] = []          # SourceEvidence 对齐的扁平证据集
    for p in pages:
        img = page_image(p, src_dpi=args.src_dpi, dpi=args.dpi)

        regions, mols, page, timing = detect_page(
            img, v3, mol_model, doc_id=p.stem, dpi=args.dpi,
            conf=args.conf, imgsz=imgsz, mol_conf=args.mol_conf,
            mol_imgsz=mol_imgsz, min_area_pct=args.min_area_pct, device=args.device,
            nms_iou=args.nms_iou)
        v3_ms, mol_ms = timing["v3_ms"], timing["mol_ms"]
        n_area_dropped += timing["area_dropped"]

        raw_regions = regions              # 未合并的 V3 原始集（供 evidence 导出用）
        n_v3_raw = len(raw_regions)
        n_mol_raw = len(mols)

        # ---- SourceEvidence 对齐导出 ----
        # 只做 M1 独有的 R1/R2；分子**扁平**输出，不建容器。
        # molecule ↔ image_region 的几何仲裁交给 MBForge 的
        # `_join_evidence_dedupe`（其规则比 M1 更激进）。
        evidence.extend(to_evidence_page(raw_regions, mols, page, doc_id=p.stem,
                                         params=merge_params))

        if args.merge:
            regions, mstats = merge_page(raw_regions, mols, page, doc_id=p.stem,
                                         params=merge_params)
            for k in mstats:
                mtot[k] = mtot.get(k, 0) + mstats[k]
            vis = draw_page_merged(img, regions, font, p.stem, mstats)
        else:
            vis = draw_page(img, regions, mols, font, p.stem)
        vis.save(outdir / f"{p.stem}.overlay.jpg", quality=88)

        n_txt = sum(1 for r in regions if r["type"] == "text")
        n_tbl = sum(1 for r in regions if r["type"] == "table")
        n_img = sum(1 for r in regions if r["type"] in ("image", "chart"))
        n_mol_out = (sum(1 for r in regions if r["type"] == "molecule")
                     + sum(len(r["children"]) for r in regions))
        row = {"page": p.stem, "n_v3": n_v3_raw, "n_text": n_txt, "n_table": n_tbl,
               "n_image": n_img, "n_mol": n_mol_raw, "n_mol_out": n_mol_out,
               "n_merged": len(regions),
               "v3_ms": round(v3_ms, 1), "mol_ms": round(mol_ms, 1)}
        all_rows.append({**row, "regions": regions, "molecules": mols})
        tot["v3"] += n_v3_raw
        tot["txt"] += n_txt
        tot["tbl"] += n_tbl
        tot["img"] += n_img
        tot["mol"] += n_mol_raw
        tot["v3ms"] += v3_ms
        tot["molms"] += mol_ms

        print(f"{p.stem[:29]:<30}{n_v3_raw:>5}{n_txt:>5}{n_tbl:>5}{n_img:>5}"
              f"{n_mol_raw:>5}{row['n_merged']:>7}{row['v3_ms']:>8.0f}{row['mol_ms']:>8.0f}")

    n = len(all_rows)
    print("-" * len(hdr))
    print(f"{'合计/平均':<30}{tot['v3']:>5}{tot['txt']:>5}{tot['tbl']:>5}{tot['img']:>5}"
          f"{tot['mol']:>5}{sum(r['n_merged'] for r in all_rows):>8}"
          f"{tot['v3ms'] / n:>8.0f}{tot['molms'] / n:>8.0f}")
    print()
    print(f"版面区域总数 : {tot['v3']}  ({tot['v3'] / n:.1f}/页)  [{args.layout}] "
          f"其中 text {tot['txt']} / table {tot['tbl']} / image+chart {tot['img']}（仅 bbox，不识别）")
    if args.min_area_pct > 0:
        print(f"  面积过滤     : 丢弃 {n_area_dropped} 个 (< {args.min_area_pct}% 页面)；"
              f"分子框豁免未过滤")
    print(f"MolDet 分子数: {tot['mol']}  ({tot['mol'] / n:.1f}/页)")
    if args.merge:
        print(f"合并后区域数 : {sum(r['n_merged'] for r in all_rows)}  "
              f"({sum(r['n_merged'] for r in all_rows) / n:.1f}/页)")
        print(f"  R1 同类去重移除 : {mtot.get('r1_dup_removed', 0)}")
        print(f"  R2 内嵌抑制     : {mtot.get('r2_suppressed', 0)}  (降级为父块 span)")
        print(f"  R5 文本框去重叠 : {mtot.get('r5_text_merged', 0)}  (有交集即并集合并)")
        print(f"  R3 1:1 让位     : {mtot.get('r3_yielded', 0)}  (image/chart → molecule)")
        print(f"  R4 1:N 容器     : {mtot.get('r4_containers', 0)} 个容器，"
              f"收纳 {mtot.get('r4_children', 0)} 个分子")
        print(f"     独立分子     : {mtot.get('molecules_standalone', 0)}")
    print(f"耗时         : {args.layout} {tot['v3ms'] / n:.1f} ms/页 | "
          f"MolDet {tot['molms'] / n:.1f} ms/页"
          f" | 合计 {(tot['v3ms'] + tot['molms']) / n:.1f} ms/页")

    summary = {
        "config": vars(args),
        "load_s": {"v3": round(v3_load, 3), "moldet": round(mol_load, 3)},
        "mol_weights": str(mol_path.name),
        "mol_imgsz": mol_imgsz,
        "merge_stats": mtot if args.merge else None,
        "area_filter": {"min_area_pct": args.min_area_pct,
                        "dropped": n_area_dropped,
                        "applies_to": "V3 only (molecules exempt)"},
        "totals": {**{k: v for k, v in tot.items() if k not in ("v3ms", "molms")},
                   "pages": n,
                   "mixed": sum(r["n_merged"] for r in all_rows),
                   "v3_per_page": round(tot["v3"] / n, 1),
                   "mol_per_page": round(tot["mol"] / n, 1),
                   "avg_v3_ms": round(tot["v3ms"] / n, 1),
                   "avg_mol_ms": round(tot["molms"] / n, 1)},
        "pages": all_rows,
    }
    (outdir / "detections.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {outdir}\\*.overlay.jpg  ({n} 张)")
    print(f"[out] {outdir}\\detections.json")

    # ---------------- SourceEvidence 对齐导出 ----------------
    from collections import Counter
    from v3 import REGION_TYPE_CATEGORY

    # 产物声明自己的 kind 词表（label → 类别），MBForge 读它把 label 映射到类别。
    # 直接从实际产出的区域汇总，所见即所得。
    kind_vocab = {}
    for row in all_rows:
        for region in row["regions"]:
            for r in (region, *region["children"]):
                kind_vocab[r["label"]] = REGION_TYPE_CATEGORY[r["type"]]

    kind_hist = Counter(e["kind"] for e in evidence)
    (outdir / "evidence.json").write_text(
        json.dumps({
            "doc_ids": sorted({e["doc_id"] for e in evidence}),
            "conventions": {"bbox": "pdf_bottom_left"},
            "kind_vocab": kind_vocab,
            "n_evidence": len(evidence),
            "kind_counts": dict(kind_hist.most_common()),
            "note": ("每个区域一条 evidence、bbox 为最小单元；evidence_id 留空由 "
                     "MBForge 按 (doc_id, page, bbox) 生成；"
                     "raw_text/coref 待识别模块补齐。"),
            "evidence": evidence,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {outdir}\\evidence.json  ({len(evidence)} 条)")
    print(f"      kind 分布: {dict(kind_hist.most_common())}")
    print(f"      kind_vocab: {len(kind_vocab)} 个 label")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M1 (PP-DocLayoutV3) 与 RapidOCR (PP-OCRv6 small) 在同批页面上的检测结果对比。

用法：
    python compare_det.py                       # 全部 Sample 页面
    python compare_det.py --samples ..\\Sample
    python compare_det.py --limit 4             # 只跑前 4 页

对比的不是"谁快"（两者任务层级不同），而是：
  1. 各自检出多少个目标（V3 区域块 vs RapidOCR 文本行框）
  2. **覆盖率**：RapidOCR 的文本行有多少落在 V3 的 text 区域里
     —— 落在里面 = V3 的文本区域划分合理
  3. **污染率**：有多少文本行落在 V3 的 image / chart 区域里
     —— 这是分子结构式内部的文字被 OCR 出来，属噪声（OCR 单跑无法自知）
  4. 有多少文本行落在任何 V3 区域之外（V3 漏检）
  5. 速度
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- 几何

def center(b):
    xs = [p[0] for p in b]
    ys = [p[1] for p in b]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def in_box(pt, box) -> bool:
    x, y = pt
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


def poly_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------- 引擎

def build_v3(device=None):
    from v3 import LayoutDetectorV3
    return LayoutDetectorV3(HERE / "weights" / "v3", device=device)


def build_ocr(engine: str, version: str, model_type: str, use_cuda: bool, full: bool):
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import EngineType, ModelType, OCRVersion

    from bench import _enum
    params = {
        "Global.log_level": "error",
        "Global.use_det": True,
        "Global.use_cls": full,
        "Global.use_rec": full,
        "Det.engine_type": _enum(EngineType, engine),
        "Det.ocr_version": _enum(OCRVersion, version),
        "Det.model_type": _enum(ModelType, model_type),
    }
    if full:
        params["Rec.engine_type"] = _enum(EngineType, engine)
        params["Rec.ocr_version"] = _enum(OCRVersion, version)
        params["Rec.model_type"] = _enum(ModelType, model_type)
    if use_cuda:
        params[f"EngineConfig.{engine}.use_cuda"] = True
    return RapidOCR(params=params)


# --------------------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--engine", default="torch")
    ap.add_argument("--version", default="PP-OCRv6")
    ap.add_argument("--model-type", default="small")
    ap.add_argument("--no-cuda", action="store_true")
    ap.add_argument("--det-only", action="store_true", help="RapidOCR 只跑 det")
    ap.add_argument("--out", default=str(HERE / "out" / "compare_det.json"))
    args = ap.parse_args()

    from PIL import Image

    pages = sorted(Path(args.samples).glob("*.png"))
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        raise SystemExit(f"没找到页面: {args.samples}")

    print(f"[cmp] {len(pages)} 页 | dpi={args.dpi} | "
          f"RapidOCR {args.engine}/{args.version}/{args.model_type}"
          f"{' det-only' if args.det_only else ' det+rec'}\n")

    t0 = time.perf_counter()
    v3 = build_v3()
    v3_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    ocr = build_ocr(args.engine, args.version, args.model_type,
                    not args.no_cuda, not args.det_only)
    ocr_load = time.perf_counter() - t0
    print(f"[load] V3 {v3_load:.2f}s | RapidOCR {ocr_load:.2f}s\n")

    rows = []
    # 预热
    _warm = Image.open(pages[0]).convert("RGB")
    _warm = _warm.resize((_warm.width // 3, _warm.height // 3), Image.LANCZOS)
    v3.predict(_warm, threshold=0.5)
    ocr(_warm)

    hdr = (f"{'page':<29}{'V3':>4}{'V3txt':>6}{'OCR行':>6}"
           f"{'覆盖%':>7}{'污染%':>7}{'漏检%':>7}{'文本区%':>8}{'图区%':>7}"
           f"{'V3ms':>8}{'OCRms':>9}")
    print(hdr)
    print("-" * len(hdr))

    for p in pages:
        img = Image.open(p).convert("RGB")
        if args.src_dpi != args.dpi:
            s = args.dpi / args.src_dpi
            img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)

        t = time.perf_counter()
        v3_items, _ = v3.predict(img, threshold=0.5)
        v3_ms = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        res = ocr(img)
        ocr_ms = (time.perf_counter() - t) * 1000

        text_regions = [i["bbox_px"] for i in v3_items if i["type"] == "text"]
        struct_regions = [i["bbox_px"] for i in v3_items
                          if i["type"] in ("image", "chart")]
        table_regions = [i["bbox_px"] for i in v3_items if i["type"] == "table"]
        all_regions = [i["bbox_px"] for i in v3_items]

        boxes = [] if res is None or res.boxes is None else res.boxes
        n_hit = n_pol = n_out = n_tbl = 0
        for b in boxes:
            c = center(b)
            if any(in_box(c, r) for r in struct_regions):
                n_pol += 1
            elif any(in_box(c, r) for r in text_regions):
                n_hit += 1
            elif any(in_box(c, r) for r in table_regions):
                n_tbl += 1
            elif not any(in_box(c, r) for r in all_regions):
                n_out += 1
            # 落在其它类型（header/footer/page_number 等）里 -> 不计
        n = max(1, len(boxes))

        def area_pct(regs):
            return sum((r[2] - r[0]) * (r[3] - r[1]) for r in regs) / (img.width * img.height) * 100

        row = {
            "page": p.stem,
            "size": f"{img.width}x{img.height}",
            "n_v3": len(v3_items),
            "n_v3_text": len(text_regions),
            "n_ocr": len(boxes),
            "cov_text": round(n_hit / n * 100, 1),
            "in_struct": round(n_pol / n * 100, 1),
            "in_table": round(n_tbl / n * 100, 1),
            "uncovered": round(n_out / n * 100, 1),
            "text_area": round(area_pct(text_regions), 1),
            "struct_area": round(area_pct(struct_regions), 1),
            "v3_ms": round(v3_ms, 1),
            "ocr_ms": round(ocr_ms, 1),
        }
        rows.append(row)
        print(f"{p.stem[:28]:<29}{row['n_v3']:>4}{row['n_v3_text']:>6}{row['n_ocr']:>6}"
              f"{row['cov_text']:>7.1f}{row['in_struct']:>7.1f}{row['uncovered']:>7.1f}"
              f"{row['text_area']:>7.1f}{row['struct_area']:>7.1f}"
              f"{row['v3_ms']:>8.0f}{row['ocr_ms']:>9.0f}")

    # 汇总
    def avg(k):
        return statistics.mean(r[k] for r in rows)

    total_v3 = sum(r["n_v3"] for r in rows)
    total_ocr = sum(r["n_ocr"] for r in rows)
    print("-" * len(hdr))
    print(f"{'合计/平均':<29}{total_v3:>4}{'':>6}{total_ocr:>6}"
          f"{avg('cov_text'):>7.1f}{avg('in_struct'):>7.1f}{avg('uncovered'):>7.1f}"
          f"{avg('text_area'):>8.1f}{avg('struct_area'):>7.1f}"
          f"{avg('v3_ms'):>8.0f}{avg('ocr_ms'):>9.0f}")
    print()
    print(f"V3 总量      : {total_v3} 个区域 / {len(rows)} 页 = {total_v3 / len(rows):.1f} 块/页")
    print(f"RapidOCR 总量: {total_ocr} 个文本行 / {len(rows)} 页 = {total_ocr / len(rows):.1f} 行/页")
    print(f"V3    平均耗时: {avg('v3_ms'):.1f} ms/页")
    print(f"OCR   平均耗时: {avg('ocr_ms'):.1f} ms/页")
    print(f"  其中落在结构式区域内（噪声）: {avg('in_struct'):.1f}% 的平均占比")

    out = {
        "config": vars(args),
        "load_s": {"v3": round(v3_load, 3), "rapidocr": round(ocr_load, 3)},
        "summary": {
            "n_pages": len(rows),
            "v3_total": total_v3, "ocr_total": total_ocr,
            "v3_per_page": round(total_v3 / len(rows), 1),
            "ocr_per_page": round(total_ocr / len(rows), 1),
            "avg_v3_ms": round(avg("v3_ms"), 1),
            "avg_ocr_ms": round(avg("ocr_ms"), 1),
            "avg_cov_text": round(avg("cov_text"), 1),
            "avg_in_struct": round(avg("in_struct"), 1),
            "avg_in_table": round(avg("in_table"), 1),
            "avg_uncovered": round(avg("uncovered"), 1),
            "avg_text_area": round(avg("text_area"), 1),
            "avg_struct_area": round(avg("struct_area"), 1),
        },
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {args.out}")


if __name__ == "__main__":
    main()

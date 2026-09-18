#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 `detections.json` 的区域按 `reading_order` 渲染出来，供**用眼**验证阅读顺序。

不重新推理 —— 只读已有 JSON + `../Sample` 的页面图，秒级出图。

图上的读法：

* 每个框左上角标 `#序号`（来自 `region["reading_order"]`）；
* 红/蓝小圆点 = 区域中心，**按序号依次连线**（第 0 个是蓝点）；
* 正确的阅读顺序：序号自上而下递增，**同一个栏内读完了才跳到下一栏**，
  连线应该是平滑的 Z 字，而不是来回横跳。

用法：
    python show_reading_order.py --run hiro_256 --pages <stem> [<stem> ...]
    python show_reading_order.py --run hiro_256_raworder --pages <stem>   # 对照旧顺序
    python show_reading_order.py --run hiro_256 --limit 3                 # 随便看 3 张
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "Sample"
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="layout/out 下的产物目录名")
    ap.add_argument("--pages", nargs="*", default=[], help="页面 stem（不含 .png）")
    ap.add_argument("--limit", type=int, default=0, help="--pages 为空时取前 N 张")
    ap.add_argument("--out", default="", help="输出目录（默认 <run>/reading_order/）")
    args = ap.parse_args()

    from PIL import Image
    from detect_overlay import draw_page_merged, get_font
    from pipeline import page_image

    run_dir = HERE / "out" / args.run
    det_path = run_dir / "detections.json"
    if not det_path.is_file():
        raise SystemExit(f"缺产物: {det_path}")

    data = json.loads(det_path.read_text(encoding="utf-8"))
    by_page = {p["page"]: p for p in data["pages"]}

    stems = args.pages or [p["page"] for p in data["pages"]][: args.limit or 5]
    outdir = Path(args.out) if args.out else run_dir / "reading_order"
    outdir.mkdir(parents=True, exist_ok=True)

    font = get_font()
    zero_stats = {"r1_dup_removed": 0, "r2_suppressed": 0,
                  "r3_yielded": 0, "r4_containers": 0}

    for stem in stems:
        pg = by_page.get(stem)
        if pg is None:
            print(f"  ! 该产物里没有 {stem}")
            continue
        img_path = SAMPLE / f"{stem}.png"
        if not img_path.is_file():
            print(f"  ! 缺页面图 {img_path.name}")
            continue
        img = page_image(img_path, src_dpi=144, dpi=144)
        dst = outdir / f"{stem}.order.jpg"
        draw_page_merged(img, pg["regions"], font, stem[:60], zero_stats).save(
            str(dst), quality=88)
        seq = [r.get("reading_order") for r in pg["regions"]]
        print(f"  {stem}  →  {dst.name}   regions={len(pg['regions'])} "
              f"order=0..{max(s for s in seq if s is not None) if any(s is not None for s in seq) else '-'}")
    print(f"\n[out] {outdir}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从专利 PDF 语料构建参考数据集（tiny / medium 两级）。

数据来源：一组专利全文 PDF（多国：WO/US/CN/TW/JP/CA/EP/KR/AU/ES/FR…）。

抽样策略：
  - 固定随机种子，可复现
  - **嵌套**：tiny 是 medium 的前若干页，便于对比规模效应而不引入样本差异
  - 以「页」为单位随机抽取（不是以「文档」为单位），避免长文档垄断

渲染：PyMuPDF，默认 384 DPI（与既有样本一致，A4 ≈ 3175×4491）。

用法：
    python build_dataset.py --src "C:\\path\\to\\pdfs" --tiny 256 --medium 1024
    python build_dataset.py --src ... --dry-run          # 只报统计不渲染
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def collect_pdfs(src: Path):
    """去重收集 PDF。

    ⚠️ 不要写成 glob('*.pdf') + glob('*.PDF') —— Windows 上两者会命中同一批文件，
    导致重复计数（实测 994 vs 实际 492）。
    """
    seen, out = set(), []
    for p in sorted(src.rglob("*")):
        if p.is_file() and p.suffix.lower() == ".pdf":
            key = str(p.resolve()).lower()
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--tiny", type=int, default=256)
    ap.add_argument("--medium", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dpi", type=int, default=384)
    ap.add_argument("--max-mp", type=float, default=40.0,
                    help="单页渲染像素上限（百万像素）。正常专利页 A4@384DPI ≈ 14 MP、"
                         "Letter ≈ 14 MP；语料里存在约 247 MP 的折叠插页（87cm 见方），"
                         "既超 PIL 防解压炸弹上限（179 MP）也不代表常规页面")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import pymupdf

    src = Path(args.src)
    if not src.exists():
        raise SystemExit(f"源目录不存在: {src}")
    out_root = Path(args.out)

    pdfs = collect_pdfs(src)
    print(f"[src ] {src}")
    print(f"[src ] 去重后 {len(pdfs)} 个 PDF")

    # 建全局页池，并记录每份 PDF 的页数
    t0 = time.perf_counter()
    pool, page_counts = [], {}
    bad, oversized = [], 0
    lim_px = args.max_mp * 1e6
    for f in pdfs:
        try:
            d = pymupdf.open(str(f))
            n = d.page_count
        except Exception as e:
            bad.append((f.name, str(e)[:50]))
            continue
        if n <= 0:
            d.close()
            continue
        page_counts[f.name] = n
        for i in range(n):
            r = d[i].rect                      # 页尺寸(pt) → 预计渲染像素
            if (r.width / 72 * args.dpi) * (r.height / 72 * args.dpi) > lim_px:
                oversized += 1
                continue
            pool.append((f, i))
        d.close()
    print(f"[pool] 总计 {len(pool)} 页（{len(page_counts)} 份可读，"
          f"{len(bad)} 份打不开），扫描耗时 {time.perf_counter() - t0:.1f}s")
    print(f"[pool] 因超过 {args.max_mp:.0f} MP 被排除的页: {oversized}")
    if bad:
        print(f"       打不开: {[b[0] for b in bad[:3]]} ...")

    need = args.medium
    if need > len(pool):
        raise SystemExit(f"页池只有 {len(pool)} 页，不够抽 {need} 页")

    rng = random.Random(args.seed)
    picked = rng.sample(pool, need)                    # medium = 全集
    tiny_set = set(range(min(args.tiny, need)))        # tiny ⊂ medium（嵌套）

    print(f"[pick] seed={args.seed}  抽 {need} 页；其中前 {len(tiny_set)} 页归 tiny")
    from collections import Counter
    pre = Counter(f.name[:2] for f, _ in picked)
    print(f"[pick] 来源分布: {dict(pre.most_common(12))}")

    if args.dry_run:
        print("[dry-run] 未渲染。")
        return

    zoom = args.dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    # 样本写到单一目录；层级（medium / tiny）记在 manifest 的 pages[].tags 里，
    # 不为每级另开目录。
    outdir = out_root / "Sample"
    outdir.mkdir(parents=True, exist_ok=True)

    # 按 PDF 分组渲染，每份只 open 一次
    by_pdf: dict[Path, list[tuple[int, set[str]]]] = {}
    for k, (f, pno) in enumerate(picked):
        tags = {"medium"} | ({"tiny"} if k in tiny_set else set())
        by_pdf.setdefault(f, []).append((pno, tags))

    done = {"medium": 0, "tiny": 0}
    made, failed = [], 0
    t0 = time.perf_counter()
    for f, items in by_pdf.items():
        try:
            doc = pymupdf.open(str(f))
        except Exception:
            failed += len(items)
            continue
        for pno, tags in items:
            try:
                pix = doc[pno].get_pixmap(matrix=mat, alpha=False)
                name = f"{f.stem}_p{pno + 1:04d}.png"
                pix.save(str(outdir / name))
                for tag in tags:
                    done[tag] += 1
                made.append({"file": name, "pdf": f.name, "page": pno + 1,
                             "w": pix.width, "h": pix.height, "tags": sorted(tags)})
            except Exception:
                failed += 1
        doc.close()
        if len(made) % 100 < len(items):
            el = time.perf_counter() - t0
            print(f"  ... {len(made)}/{need} 页完成，{el:.0f}s，"
                  f"约 {el / max(1, len(made)) * 1000:.0f} ms/页", flush=True)

    print(f"\n[done] tiny {done['tiny']} 张 | medium {done['medium']} 张 | 失败 {failed}")
    print(f"       耗时 {time.perf_counter() - t0:.0f}s")
    (out_root / "dataset_manifest.json").write_text(
        json.dumps({"src": str(src), "seed": args.seed, "dpi": args.dpi,
                    "max_mp": args.max_mp, "n_pdfs": len(pdfs),
                    "n_pages_in_pool": len(pool), "oversized_excluded": oversized,
                    "tiny": done["tiny"], "medium": done["medium"],
                    "note": "tiny ⊂ medium（嵌套抽样）；文件名 {patent_stem}_p{page:04d}.png；"
                            "已排除渲染像素 > max_mp 的折叠插页",
                    "pages": made}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out ] {out_root / 'dataset_manifest.json'}")


if __name__ == "__main__":
    main()

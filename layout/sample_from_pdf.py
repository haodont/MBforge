#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从 PDF 随机抽样页面，把样本集补足到目标张数。

单文件模式把样本补足到目标张数；目录模式跨多个 PDF 全局随机抽 N 张。

用法：
    python sample_from_pdf.py --pdf "C:\\path\\to\\x.pdf" --target 100
    python sample_from_pdf.py --pdf ... --target 100 --seed 42 --dry-run
    python sample_from_pdf.py --pdf-dir "C:\\path\\to\\pdfs" --target 256 \
        --dpi 144 --out-dir ..\\Sample
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "Sample"


def safe_name(s: str) -> str:
    """清掉换行与 Windows 非法文件名字符。

    踩过的坑：从 PDF 文本里正则抠公布号，会把换行一起抠进来
    （'CN\\n202410166244'），存盘时报 `cannot remove file ... Invalid argument`。
    而且那串其实是优先权号不是公布号。故默认直接用 PDF 文件名做前缀。
    """
    for ch in '\r\n\t':
        s = s.replace(ch, "")
    for ch in '<>:"/\\|?*':
        s = s.replace(ch, "_")
    return s.strip().strip("_") or "sample"


def sample_dir(args):
    """跨目录内所有 PDF 全局随机抽 N 张页。"""
    import pymupdf

    srcdir = Path(args.pdf_dir)
    if not srcdir.is_dir():
        raise SystemExit(f"目录不存在: {srcdir}")

    pdfs = sorted(p for p in srcdir.iterdir()
                  if p.suffix.lower() == args.glob.lower().lstrip("*"))
    if not pdfs:
        raise SystemExit(f"{srcdir} 下没有匹配 {args.glob} 的文件")

    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 建全局 (pdf, page) 池
    pool = []
    for p in pdfs:
        try:
            n = pymupdf.open(str(p)).page_count
        except Exception as e:
            print(f"[skip] {p.name}: {e}")
            continue
        pool.extend((p, pno) for pno in range(1, n + 1))

    print(f"[src]  {srcdir}")
    print(f"[pdf]  {len(pdfs)} 个 PDF，共 {len(pool)} 页")
    print(f"[out]  {outdir}")
    print(f"[dpi]  {args.dpi}")

    rng = random.Random(args.seed)
    rng.shuffle(pool)
    picked = pool[: args.target]
    print(f"[pick] seed={args.seed} 抽 {len(picked)} 页"
          f"{'（池不足，实际抽 ' + str(len(picked)) + '）' if len(picked) < args.target else ''}")

    if args.dry_run:
        for p, pno in picked[:20]:
            print(f"   {p.name} p{pno}")
        print("[dry-run] 未写文件。")
        return

    mat = pymupdf.Matrix(args.dpi / 72.0, args.dpi / 72.0)
    doc = None
    cur = None
    made = []
    for i, (p, pno) in enumerate(picked, 1):
        if cur != p:
            if doc is not None:
                doc.close()
            doc = pymupdf.open(str(p))
            cur = p
        pix = doc[pno - 1].get_pixmap(matrix=mat, alpha=False)
        name = f"{safe_name(p.stem)}_p{pno:04d}.png"
        dst = outdir / name
        pix.save(str(dst))
        made.append({"file": name, "pdf": p.name, "pdf_page": pno,
                     "w": pix.width, "h": pix.height,
                     "kb": round(dst.stat().st_size / 1024)})
        if i % 25 == 0 or i == len(picked):
            print(f"  {i}/{len(picked)}  {name}  {pix.width}x{pix.height}")
    if doc is not None:
        doc.close()

    manifest = {
        "source": str(srcdir), "seed": args.seed, "dpi": args.dpi,
        "target": args.target, "n_pdfs": len(pdfs), "n_pages_pool": len(pool),
        "added": made,
    }
    (outdir / "_pdf_samples.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] 渲染 {len(made)} 张 → {outdir}")
    print(f"[out]  {outdir}\\_pdf_samples.json")


def sample_single(args):
    """单 PDF 模式：把样本集补足到目标张数（原行为）。"""
    import pymupdf

    pdf = Path(args.pdf)
    if not pdf.exists():
        raise SystemExit(f"PDF 不存在: {pdf}")

    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    existing = sorted(outdir.glob("*.png"))
    need = args.target - len(existing)

    doc = pymupdf.open(str(pdf))
    print(f"[pdf]  {pdf.name}  {doc.page_count} 页")
    print(f"[out]  {outdir}")
    print(f"[data] 现有 {len(existing)} 张 → 目标 {args.target} → 需抽 {max(0, need)} 张")
    if need <= 0:
        print("已达标，无需抽样。")
        return

    # 前缀：默认用 PDF 文件名（清洗非法字符）
    prefix = safe_name(args.prefix or pdf.stem)
    print(f"[name] 前缀 = {prefix}")

    # 固定种子随机抽样，避开已存在的页号（若文件名里带 _p<num>）
    rng = random.Random(args.seed)
    pool = list(range(1, doc.page_count + 1))
    rng.shuffle(pool)
    picked = sorted(pool[:need])

    zoom = args.dpi / 72.0
    print(f"[dpi]  {args.dpi} (zoom={zoom:.4f})")
    print(f"[pick] seed={args.seed} 页号: {picked[:20]}{' ...' if len(picked) > 20 else ''}")

    if args.dry_run:
        print("[dry-run] 未写文件。")
        return

    mat = pymupdf.Matrix(zoom, zoom)
    made = []
    for i, pno in enumerate(picked, 1):
        pg = doc[pno - 1]
        pix = pg.get_pixmap(matrix=mat, alpha=False)
        name = f"{prefix}_p{pno:04d}.png"
        dst = outdir / name
        pix.save(str(dst))
        made.append({"file": name, "pdf_page": pno,
                     "w": pix.width, "h": pix.height,
                     "kb": round(dst.stat().st_size / 1024)})
        if i % 10 == 0 or i == len(picked):
            print(f"  {i}/{len(picked)}  {name}  {pix.width}x{pix.height}")

    total = len(list(outdir.glob("*.png")))
    print(f"\n[done] 新增 {len(made)} 张，样本集现共 {total} 张")
    (outdir / "_pdf_samples.json").write_text(
        json.dumps({"pdf": str(pdf), "seed": args.seed, "dpi": args.dpi,
                    "prefix": prefix, "added": made}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[out]  {outdir}\\_pdf_samples.json（记录页号，便于溯源/复现）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="", help="单个 PDF（补足模式）")
    ap.add_argument("--pdf-dir", default="", help="PDF 目录（跨文件全局随机抽样模式）")
    ap.add_argument("--glob", default="*.pdf", help="--pdf-dir 下的文件匹配（默认 *.pdf）")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--target", type=int, default=100, help="目标总张数")
    ap.add_argument("--seed", type=int, default=42, help="随机种子（固定以便复现）")
    ap.add_argument("--dpi", type=int, default=144, help="渲染 DPI（与 ../Sample 一致）")
    ap.add_argument("--prefix", default="", help="文件名前缀，默认取申请公布号")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.pdf_dir:
        if not args.out_dir:
            args.out_dir = str(HERE.parent / "Sample")
        args.glob = args.glob or "*.pdf"
        sample_dir(args)
    elif args.pdf:
        if not args.out_dir:
            args.out_dir = str(DEFAULT_OUT)
        sample_single(args)
    else:
        ap.error("需要 --pdf 或 --pdf-dir")


if __name__ == "__main__":
    main()

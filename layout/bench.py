#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M1(V3) 与 RapidOCR 的同页速度对比基准。

用法：
    python bench.py --runs 3
    python bench.py --engine torch --model-type server --runs 3
    python bench.py --ocr-only --engine torch

说明：
  - 图像统一降采样到 144 DPI（DESIGN.md §3.1 契约），两套都在同一分辨率上跑。
  - M1 的计时不含 M0 降采样（降采样单独计）。
  - RapidOCR 计时含 det+cls+rec 全流程，与 M1 的"只出区域"口径不同，
    因此**两者不可直接比快慢**，只能各自看绝对量级。见 README 的说明。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES = sorted((HERE.parent / "Sample").glob("*.png"))


def timed(fn, runs: int):
    """跑 runs 次，返回 (首次秒, 中位秒, 全部秒列表)。"""
    ts = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return ts[0], statistics.median(ts), ts


def bench_m1(images, runs: int, device: str | None):
    import torch
    from PIL import Image

    from v3 import LayoutDetectorV3, build_regions

    det = LayoutDetectorV3(HERE / "weights" / "v3", device=device)
    warm = images[0]["image"]
    det.predict(warm, threshold=0.5)          # 预热
    rows = []
    for item in images:
        img = item["image"]
        _, med, ts = timed(lambda: det.predict(img, threshold=0.5), runs)
        items, page_px = det.predict(img, threshold=0.5)
        rows.append({
            "page": item["name"], "n_regions": len(items),
            "median_s": round(med, 4),
            "all_s": [round(t, 4) for t in ts],
        })
    del det
    torch.cuda.empty_cache()
    return rows


def _enum(enum_cls, value):
    """把字符串解析成 rapidocr 的枚举成员。

    rapidocr 3.9.x 要求 params 里的取值是 Enum 实例，传字符串会抛
    TypeError: The value of Det.engine_type must be Enum Type.
    """
    if not isinstance(value, str):
        return value
    key = "".join(ch for ch in value.upper() if ch.isalnum())   # "PP-OCRv6" -> "PPOCRV6"
    for name in dir(enum_cls):
        if name.startswith("_"):
            continue
        if name.upper() == key:
            return getattr(enum_cls, name)
    raise ValueError(f"{enum_cls.__name__} 无成员 {value!r}；可用: "
                     f"{[n for n in dir(enum_cls) if not n.startswith('_')]}")


def bench_rapidocr(images, runs: int, engine: str, version: str, model_type: str,
                   use_cuda: bool = False):
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import EngineType, ModelType, OCRVersion

    eng = _enum(EngineType, engine)
    ver = _enum(OCRVersion, version)
    mty = _enum(ModelType, model_type)

    t0 = time.perf_counter()
    params = {
        "Global.log_level": "error",
        "Det.engine_type": eng, "Det.ocr_version": ver, "Det.model_type": mty,
        "Rec.engine_type": eng, "Rec.ocr_version": ver, "Rec.model_type": mty,
        "Cls.engine_type": eng,
    }
    if use_cuda:
        # ⚠️ rapidocr 默认 use_cuda=False（torch 与 onnxruntime 都是），
        #    不显式打开就会在 CPU 上跑，速度差一个量级。
        params[f"EngineConfig.{engine}.use_cuda"] = True
    ocr = RapidOCR(params=params)
    load_s = time.perf_counter() - t0

    warm = images[0]["image"]
    ocr(warm)                                  # 预热（含模型下载）
    rows = []
    for item in images:
        img = item["image"]

        def run():
            r = ocr(img)
            n = 0 if r is None or r.txts is None else len(r.txts)
            return n

        n_txt = run()
        _, med, ts = timed(run, runs)
        rows.append({
            "page": item["name"], "n_texts": int(n_txt),
            "median_s": round(med, 4),
            "all_s": [round(t, 4) for t in ts],
        })
    return load_s, rows


def load_images(dpi: int, src_dpi: int):
    from PIL import Image
    out = []
    for p in SAMPLES:
        im = Image.open(p).convert("RGB")
        assert isinstance(im, Image.Image)
        if src_dpi != dpi:
            s = dpi / src_dpi
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        out.append({"name": p.stem, "image": im,
                    "size": f"{im.width}x{im.height}"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--engine", default="torch", help="torch / onnxruntime / openvino")
    ap.add_argument("--version", default="PP-OCRv6")
    ap.add_argument("--model-type", default="small", help="small / server / medium / mobile")
    ap.add_argument("--use-cuda", action="store_true",
                    help="打开 rapidocr 的 GPU（默认关闭，不开就是 CPU 跑）")
    ap.add_argument("--device", default=None)
    ap.add_argument("--skip-m1", action="store_true")
    ap.add_argument("--skip-ocr", action="store_true")
    ap.add_argument("--out", default=str(HERE / "out" / "bench.json"))
    args = ap.parse_args()

    print(f"[bench] samples={len(SAMPLES)} runs={args.runs} dpi={args.dpi}\n")
    images = load_images(args.dpi, args.src_dpi)
    for it in images:
        print(f"  {it['name']:<26} {it['size']}")
    result = {"runs": args.runs, "dpi": args.dpi, "config": vars(args)}

    if not args.skip_m1:
        print("\n" + "=" * 74)
        print("M1 LayoutDetection (PP-DocLayoutV3, transformers/PyTorch)")
        print("=" * 74)
        t0 = time.perf_counter()
        rows = bench_m1(images, args.runs, args.device)
        result["m1"] = {"load_s": round(time.perf_counter() - t0, 3), "rows": rows}
        for r in rows:
            print(f"  {r['page']:<26} regions={r['n_regions']:<4} "
                  f"median={r['median_s'] * 1000:8.1f} ms   all={[round(t * 1000, 1) for t in r['all_s']]} ms")
        tot = sum(r["median_s"] for r in rows)
        print(f"  {'合计(中位相加)':<26} {tot * 1000:.1f} ms  "
              f"→ {tot / len(rows) * 1000:.1f} ms/页")

    if not args.skip_ocr:
        print("\n" + "=" * 74)
        print(f"RapidOCR ({args.engine} / {args.version} / {args.model_type}"
              f"{' / CUDA' if args.use_cuda else ' / CPU'})")
        print("=" * 74)
        try:
            load_s, rows = bench_rapidocr(images, args.runs, args.engine,
                                          args.version, args.model_type, args.use_cuda)
            result["rapidocr"] = {"load_s": round(load_s, 3), "rows": rows,
                                  "engine": args.engine, "version": args.version,
                                  "model_type": args.model_type,
                                  "use_cuda": args.use_cuda}
            print(f"  加载: {load_s:.2f} s")
            for r in rows:
                print(f"  {r['page']:<26} texts={r['n_texts']:<5} "
                      f"median={r['median_s'] * 1000:8.1f} ms   all={[round(t * 1000, 1) for t in r['all_s']]} ms")
            tot = sum(r["median_s"] for r in rows)
            print(f"  {'合计(中位相加)':<26} {tot * 1000:.1f} ms  "
                  f"→ {tot / len(rows) * 1000:.1f} ms/页")
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")
            result["rapidocr_error"] = f"{type(e).__name__}: {e}"

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {args.out}")


if __name__ == "__main__":
    main()

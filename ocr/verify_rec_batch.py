#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证 RapidOCR 的**批量 rec 调用**（只用 PP-OCRv6 的 rec 模型）。

## 接口分析结论

`RapidOCR.__call__(img_content)` 只收**单张**图，无批量。但内部步骤是公开方法，
可以直接拆开用：

    preprocess_img(ori_img)          -> (img, op_record)      缩放/padding
    detect_and_crop(img, op_record)  -> (crops, det_res)      检测 + 裁剪
    recognize_txt(crops: List[np.ndarray]) -> TextRecOutput   ★ 批量 rec 入口
    filter_by_text_score(ocr_res)    -> 按 text_score 过滤

`recognize_txt` 内部构造 `TextRecInput(img=crops)`，而 `TextRecInput.img` 的类型是
`np.ndarray | List[np.ndarray]` —— **原生支持批量**，且 `TextRecognizer.__call__`
会按 `rec_batch_num`（默认 6）自动分批，并按宽高比排序提速。

## 两个坑

1. **不要给共享实例传 `use_rec=False`**。实测传过一次之后，后续 `ocr(img)` 也返回
   `TextDetOutput`（实例状态被改写了），会炸在 `.txts` 上。要单独检测请用
   `preprocess_img + detect_and_crop`。
2. **裁剪必须在 `preprocess_img` 之后的图 + `detect_and_crop` 的内部步骤上做**，
   自己拿原图 + 原图坐标裁会错位（因为全流程先缩放再 padding 再检测）。

本脚本验证：批量 rec 的文本与全流程**逐行一致**，并给出 det / rec 的分段耗时。
"""

from __future__ import annotations

import argparse
import time
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="PPOCRV6")
    ap.add_argument("--model-type", default="SMALL")
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--pages", type=int, default=10)
    args = ap.parse_args()

    import cv2
    import numpy as np
    from PIL import Image

    pages = sorted(Path(args.samples).glob("*.png"))[: args.pages]
    arrs = []
    for p in pages:
        im = Image.open(p).convert("RGB")
        if args.src_dpi != args.dpi:
            s = args.dpi / args.src_dpi
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        arrs.append((p.stem, cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)))

    ocr = build(args.version, args.model_type)
    ocr(arrs[0][1])                                   # 预热
    ts = ocr.cfg.Global.text_score

    print(f"[cfg] {args.version} / {args.model_type}（torch+CUDA，cls 关闭，"
          f"text_score={ts}）")
    print(f"[rec] rec_batch_num={ocr.text_rec.rec_batch_num} "
          f"rec_img_shape={list(ocr.text_rec.rec_image_shape)}")
    print(f"[cmp] {len(arrs)} 页\n")

    t_full = t_det = t_rec = 0.0
    n_lines = n_batch = 0
    bad = 0
    print(f"{'page':<32}{'全流程行':>9}{'批量行':>8}{'全流程ms':>10}{'det_ms':>8}{'rec_ms':>8}{'一致':>6}")
    for stem, arr in arrs:
        # A. 全流程（det + rec + 过滤）
        t = time.perf_counter()
        full = ocr(arr)
        ms_full = (time.perf_counter() - t) * 1000
        t_full += ms_full
        ref = list(full.txts) if full is not None and full.txts is not None else []

        # B. 拆开：preprocess+det ｜ 批量 rec
        t = time.perf_counter()
        img, op = ocr.preprocess_img(arr)
        crops, det_res = ocr.detect_and_crop(img, op)
        ms_det = (time.perf_counter() - t) * 1000
        t_det += ms_det

        t = time.perf_counter()
        rec = ocr.recognize_txt(crops)                 # ★ 批量入口
        ms_rec = (time.perf_counter() - t) * 1000
        t_rec += ms_rec
        # 与全流程同口径：套用 text_score 过滤
        got = [t_ for t_, s in zip(rec.txts, rec.scores) if s >= ts] if rec.txts else []

        same = got == ref
        bad += 0 if same else 1
        n_lines += len(ref)
        n_batch += len(got)
        print(f"{stem[:31]:<32}{len(ref):>9}{len(got):>8}{ms_full:>10.0f}"
              f"{ms_det:>8.0f}{ms_rec:>8.0f}{'✓' if same else '✗':>6}")
        if not same and bad <= 2:
            for i, (x, y) in enumerate(zip(ref, got)):
                if x != y:
                    print(f"      #{i}\n        full : {x[:70]!r}\n        batch: {y[:70]!r}")
                    break

    n = len(arrs)
    print()
    print(f"行数           : 全流程 {n_lines}  批量 {n_batch}")
    print(f"逐行一致性     : {'全部一致 ✓' if bad == 0 else f'{bad}/{n} 页不一致 ✗'}")
    print()
    print(f"耗时           : 全流程 {t_full / n:7.0f} ms/页")
    print(f"                 det  {t_det / n:7.0f} ms/页")
    print(f"                 rec  {t_rec / n:7.0f} ms/页（批量，一次调用）")
    print(f"                 det+rec = {(t_det + t_rec) / n:.0f} ms/页")


if __name__ == "__main__":
    main()

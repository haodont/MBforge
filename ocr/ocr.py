#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文本识别（ocr）：**版面识别的 text 框 → 块内行检测 → 逐行批量识别 → 回填 raw_text**

## 形态（为什么这么切）

不能整页裸跑 det：实测整页 OCR 有 37–42% 的识别行落在结构式内部
（`F`/`N`/`O` 这类原子符号），全是污染。

也不能"每个块各调一次 `ocr(crop)`"：实测那样 303 ms/块 × 6 块 = **1537 ms/页**，
比整页还慢 —— 固定开销被块数放大了。

所以按 RapidOCR 的内部步骤拆开：

    每个 text 框:  preprocess_img → detect_and_crop → map_boxes_to_original
                   （只做 det，把行裁剪攒起来）
    每页最后:      recognize_txt(全部行裁剪)   ← ★ 一次批量调用，按 rec_batch_num 自动分批

这样固定开销只付一次，同时检测被限制在文本区内、不碰结构式。

## 输入 / 输出

输入：版面识别的 `detections.json`（提供 text 框）+ 页面图像（144 DPI）
输出：`out/ocr.json`                —— 行级明细 + 每框的 raw_text
      `out/evidence_with_text.json` —— MBForge SourceEvidence 形状，`raw_text` 已填

用法：
    python ocr.py                       # 全样本
    python ocr.py --limit 10
    python ocr.py --model-type TINY
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 文本区域的判据：**按生产者给的 `kind`，不要按 `label`**。
#
# `label` 是检测器词表，V3 与 Hiro 各不相同。按 label 匹配时，Hiro 只有 `text` 能命中，
# `sec` / `mnote` / `cap` / `figno` / `lineno` / `colno` / `ref` / `toc` / `bib`
# 这 9 类文本全部落空 —— 实测 1900 个 `text_span` 只能取到 1635 个。
# `kind` 由 `layout/v3.py::KIND_MAP` 统一产出，与用哪个检测器无关。
# （与 `merge.py` 的 R3/R4 按 RegionType 匹配是同一原则。）
TEXT_KIND = "text_span"


_CJK_MIN = 0x2E80          # CJK 部首起；含中日韩文字与全角标点（：，。（）等）
_NO_SPACE_AFTER = set("-([{/")   # 断词连字符、左括号、斜杠之后不补空格


def _is_cjk(ch: str) -> bool:
    return ord(ch) >= _CJK_MIN


def _needs_space(a: str, b: str) -> bool:
    """两行拼接处是否该补空格。

    - 任一侧是 CJK（含全角标点）→ 不补（中文无词间空格）
    - 上一行以 `-([{/` 结尾 → 不补（断词连字符、行内左括号/斜杠）
    - 其余 → 补（英文语境）
    """
    if _is_cjk(a) or _is_cjk(b):
        return False
    return a not in _NO_SPACE_AFTER


def join_lines(texts):
    """按行拼接 raw_text，处理中英混排的换行。

    判据是 CJK，而不是"两侧都是 ASCII 字母数字"：后者在英文**标点处**换行时会漏空格，
    产出 `redness,swelling`、`M2),comparisons`、`;MacDonald` 这类粘连。
    规则：只要两侧都不是 CJK 就补空格（除断词连字符与左括号/斜杠）。
    """
    out = ""
    for t in texts:
        if not t:
            continue
        if out and _needs_space(out[-1], t[0]):
            out += " "
        out += t
    return out


def build(version: str, model_type: str, cuda: bool = True):
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import EngineType, ModelType, OCRVersion

    return RapidOCR(params={
        "Global.log_level": "error",
        "Global.use_cls": False,                       # 关闭方向分类，保持坐标系
        "Det.engine_type": EngineType.TORCH, "Det.ocr_version": getattr(OCRVersion, version),
        "Det.model_type": getattr(ModelType, model_type),
        "Rec.engine_type": EngineType.TORCH, "Rec.ocr_version": getattr(OCRVersion, version),
        "Rec.model_type": getattr(ModelType, model_type),
        "EngineConfig.torch.use_cuda": cuda,
    })


class TextOCR:
    """按版面识别的 text 框做行级 OCR。每页只调一次批量 rec。

    两种口径：

    ``arch="block"``（逐块 det）
        对每个 text 框单独跑 det。**注意**：RapidOCR 的 det 配置是
        `limit_side_len=736, limit_type=min`，即**短边不得小于 736**。
        整页（1190×1684）短边已够、不缩放；但文本块如 939×174 会被**放大 4.2 倍**
        到 4046×736，比整页还大 —— 实测因而 1712 ms/页，比整页口径还慢。

    ``arch="page"``（整页 det + 按版面识别框过滤）
        整页只 det 一次（204 ms），把行按中心点是否落在版面识别的 text 框内过滤，
        再对保留的行做一次批量 rec。检测尺度合理，且结构式内的行被整片滤掉。
    """

    def __init__(self, version="PPOCRV6", model_type="SMALL", cuda=True):
        self.ocr = build(version, model_type, cuda)
        self.version = version
        self.model_type = model_type

    # ---------------------------------------------------------------- 逐块 det
    def _by_block(self, arr_bgr, boxes):
        from rapidocr.utils.process_img import map_boxes_to_original

        H, W = arr_bgr.shape[:2]
        crops_all, meta_all = [], []
        n_ok = 0
        for rid, (bx0, by0, bx1, by1) in boxes:
            x0 = int(max(0, min(W - 1, bx0)))
            y0 = int(max(0, min(H - 1, by0)))
            x1 = int(max(x0 + 1, min(W, bx1)))
            y1 = int(max(y0 + 1, min(H, by1)))
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            sub = arr_bgr[y0:y1, x0:x1]
            try:
                img2, op = self.ocr.preprocess_img(sub)
                crops, det = self.ocr.detect_and_crop(img2, op)
            except Exception:
                continue                                   # 该块 det 失败 -> 跳过（失败隔离）
            if not crops:
                continue
            n_ok += 1
            try:
                boxes_ori = map_boxes_to_original(det.boxes, op, sub.shape[0], sub.shape[1])
            except Exception:
                boxes_ori = det.boxes
            for c, b in zip(crops, boxes_ori):
                xs = [float(p[0]) for p in b]
                ys = [float(p[1]) for p in b]
                crops_all.append(c)
                meta_all.append({"region_id": rid,
                                 "bbox_px": [round(min(xs) + x0, 2), round(min(ys) + y0, 2),
                                             round(max(xs) + x0, 2), round(max(ys) + y0, 2)]})
        return crops_all, meta_all, n_ok

    # ------------------------------------------- 整页 det + 按版面识别框过滤
    def _by_page(self, arr_bgr, boxes):
        import numpy as np
        from rapidocr.utils.process_img import map_boxes_to_original

        img2, op = self.ocr.preprocess_img(arr_bgr)
        crops, det = self.ocr.detect_and_crop(img2, op)
        H, W = arr_bgr.shape[:2]
        boxes_ori = map_boxes_to_original(det.boxes, op, H, W)

        def center_in_page_box(b):
            cx = (float(b[:, 0].min()) + float(b[:, 0].max())) / 2
            cy = (float(b[:, 1].min()) + float(b[:, 1].max())) / 2
            for rid, (x0, y0, x1, y1) in boxes:
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    return rid
            return None

        crops_all, meta_all = [], []
        for c, b in zip(crops, boxes_ori):
            rid = center_in_page_box(np.asarray(b))
            if rid is None:
                continue                     # 落在版面识别文本区之外 -> 丢弃（结构式内部）
            xs = [float(p[0]) for p in b]
            ys = [float(p[1]) for p in b]
            crops_all.append(c)
            meta_all.append({"region_id": rid,
                             "bbox_px": [round(min(xs), 2), round(min(ys), 2),
                                         round(max(xs), 2), round(max(ys), 2)]})
        return crops_all, meta_all, len(boxes)

    # ---------------------------------------------------------------- 统一入口
    def run_page(self, arr_bgr, boxes, arch="page"):
        """boxes: [(region_id, (x0,y0,x1,y1))]，返回 (lines, stats, ms)"""
        t0 = time.perf_counter()
        if arch == "block":
            crops_all, meta_all, n_ok = self._by_block(arr_bgr, boxes)
        else:
            crops_all, meta_all, n_ok = self._by_page(arr_bgr, boxes)

        if not crops_all:
            return [], {"blocks": n_ok, "crops": 0}, (time.perf_counter() - t0) * 1000

        rec = self.ocr.recognize_txt(crops_all)            # ★ 一次批量 rec
        ms = (time.perf_counter() - t0) * 1000

        lines = []
        for m, txt, sc in zip(meta_all, rec.txts or [], rec.scores or []):
            lines.append({**m, "text": txt, "score": round(float(sc), 4)})
        return lines, {"blocks": n_ok, "crops": len(crops_all)}, ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detections", default=str(HERE.parent / "layout" / "out" /
                                                "hiro_256" / "detections.json"))
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--version", default="PPOCRV6")
    ap.add_argument("--model-type", default="SMALL")
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--src-dpi", type=int, default=144)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--arch", default="page", choices=["page", "block"],
                    help="page=整页 det + 按版面识别框过滤（默认）；block=逐块 det")
    ap.add_argument("--out", default=str(HERE / "out"))
    args = ap.parse_args()

    import cv2
    import numpy as np
    from PIL import Image

    det_path = Path(args.detections)
    if not det_path.exists():
        raise SystemExit(f"缺少版面识别的产物: {det_path}\n请先在 layout/ 跑 detect_overlay.py")
    layout_det = json.loads(det_path.read_text(encoding="utf-8"))
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    jobs = []
    for p in layout_det["pages"]:
        boxes = [(r["region_id"], r["bbox_px"]) for r in p["regions"]
                 if r.get("kind") == TEXT_KIND]
        if boxes:
            jobs.append((p["page"], boxes))
    if args.limit:
        jobs = jobs[: args.limit]

    print(f"[layout] 读入 {len(layout_det['pages'])} 页；本次处理 {len(jobs)} 页")
    print(f"[ocr] {args.version} / {args.model_type}，arch={args.arch}，cls 关闭，torch+CUDA")

    ocr = TextOCR(args.version, args.model_type, cuda=True)
    print(f"     rec_batch_num={ocr.ocr.text_rec.rec_batch_num} "
          f"rec_img_shape={list(ocr.ocr.text_rec.rec_image_shape)}\n")

    tot_blk = tot_crop = tot_line = 0
    ms_list = []
    pages_out = []
    hdr = f"{'page':<34}{'块':>5}{'行裁剪':>8}{'行':>7}{'ms':>8}"
    print(hdr)
    print("-" * len(hdr))

    for stem, boxes in jobs:
        img_path = Path(args.samples) / f"{stem}.png"
        if not img_path.exists():
            print(f"  ! 缺图: {img_path.name}")
            continue
        im = Image.open(img_path).convert("RGB")
        if args.src_dpi != args.dpi:
            s = args.dpi / args.src_dpi
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        arr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)

        lines, stats, ms = ocr.run_page(arr, boxes, arch=args.arch)
        ms_list.append(ms)
        px_per_pt = args.dpi / 72.0
        h_pt = arr.shape[0] / px_per_pt
        for ln in lines:
            x0, y0, x1, y1 = (float(v) for v in ln["bbox_px"])
            ln["bbox_pdf"] = [round(v, 2) for v in
                              (x0 / px_per_pt, h_pt - y1 / px_per_pt,
                               x1 / px_per_pt, h_pt - y0 / px_per_pt)]

        # 按框聚合 raw_text：行序 = 版面顺序（先 y 后 x）
        per_region = {}
        for rid, _ in boxes:
            sub = sorted([ln for ln in lines if ln["region_id"] == rid],
                         key=lambda z: (z["bbox_px"][1], z["bbox_px"][0]))
            per_region[rid] = join_lines([ln["text"] for ln in sub])
        tot_blk += stats.get("blocks", 0)
        tot_crop += stats.get("crops", 0)
        tot_line += len(lines)
        pages_out.append({"page": stem, "width_px": arr.shape[1], "height_px": arr.shape[0],
                          "dpi": args.dpi, "lines": lines, "region_text": per_region})
        print(f"{stem[:33]:<34}{stats.get('blocks', 0):>5}{stats.get('crops', 0):>8}"
              f"{len(lines):>7}{ms:>8.0f}")

    n = len(ms_list) or 1
    print("-" * len(hdr))
    print(f"{'合计/平均':<34}{tot_blk:>5}{tot_crop:>8}{tot_line:>7}{st.median(ms_list):>8.0f}")
    print()
    print(f"块总数        : {tot_blk}  ({tot_blk / n:.1f}/页)")
    print(f"行裁剪总数    : {tot_crop}  ({tot_crop / n:.1f}/页)  ← 每页一次批量 rec")
    print(f"识别行总数    : {tot_line}  ({tot_line / n:.1f}/页)")
    print(f"耗时          : 中位 {st.median(ms_list):.0f} ms/页  "
          f"均值 {st.mean(ms_list):.0f} ms/页")

    (outdir / "ocr.json").write_text(
        json.dumps({"config": vars(args), "pages": pages_out},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 投影成 MBForge SourceEvidence 形状，raw_text 已填 ----
    ev = []
    for pg in pages_out:
        stem = pg["page"]
        for r in next(x for x in layout_det["pages"] if x["page"] == stem)["regions"]:
            if r.get("kind") != TEXT_KIND:
                continue
            txt = pg["region_text"].get(r["region_id"], "").strip()
            if not txt:
                continue                                   # 无文本不产出（evidence 要求非空）
            ev.append({"doc_id": r["doc_id"], "page": r["page"], "evidence_id": "",
                       "bbox": list(r["bbox_pdf"]), "raw_text": txt, "coref": "",
                       "kind": TEXT_KIND,
                       "_m1": {"region_id": r["region_id"], "label": r["label"],
                               "reading_order": r.get("reading_order"),
                               "score": r["score"], "bbox_px": r["bbox_px"]}})
    (outdir / "evidence_with_text.json").write_text(
        json.dumps({"conventions": {"bbox": "pdf_bottom_left"},
                    "n_evidence": len(ev),
                    "note": "text_span 的 raw_text 已由文本识别填充；"
                            "image_region / molecule / table_span 仍待各自的识别模块",
                    "evidence": ev}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {outdir / 'ocr.json'}  （行级明细 + 每框 raw_text）")
    print(f"[out] {outdir / 'evidence_with_text.json'}  （{len(ev)} 条 text_span 已带 raw_text）")


if __name__ == "__main__":
    main()

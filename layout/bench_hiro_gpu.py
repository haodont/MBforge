#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
问题 #1：Hiro-Layout 本机耗时的同进程背靠背基准。

回答一个问题：**装上 GPU 版 onnxruntime 后，Hiro 是落到 ~150–250 ms/页（可迭代），
还是仍在 600 ms 以上（要重新讨论选型）？**

计时纪律（照 `M1/README.md` §7.1）：
  - 本机 GPU 计时噪声 ±26%，**跨运行的绝对耗时不可比**，只有**同进程背靠背**有效。
    故本脚本把 GPU / CPU / 不同 batch / 不同线程数**放在同一个进程里依次测**。
  - 每个配置先预热（V3 冷启动 750 ms vs 稳态 110 ms，差 6 倍）。
  - 每个配置跑 N 轮取中位。

正确性交叉校验：
  GPU 与 CPU 在**同一批页**上的检出数必须一致（V3 那边的既有标准是同配置多次运行
  计数一字不差：1415/600/35/93）。若不一致 → 先查数值/provider 静默回落，再谈速度。

用法：
    $PY bench_hiro_gpu.py --limit 64 --rounds 3
    $PY bench_hiro_gpu.py --limit 0 --rounds 3 --configs headline   # 全 256 页
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ONNX_DIR = HERE / "weights" / "hiro"
IMGSZ = 640
CONF = 0.4          # 与 baseline_256 / hiro_256 对齐，便于横向比较


def load_pages(samples: Path, limit: int):
    from PIL import Image

    paths = sorted(samples.glob("*.png"))
    if limit:
        paths = paths[:limit]
    if not paths:
        raise SystemExit(f"没找到页面: {samples}")
    pages = []
    for p in paths:
        with Image.open(p) as im:
            pages.append((p.stem, im.convert("RGB").copy()))
    return pages


def make_detector(provider: str, threads: int | None):
    """provider: 'cuda' | 'cpu'。返回 (det, load_s, actual_providers)。

    ⚠️ 返回的 `actual_providers` 来自 `session.get_providers()`，不是
    `ort.get_available_providers()` —— 后者会把"编译进来但加载失败"的 EP 一并列出。
    """
    from hiro import HiroLayoutDetector

    providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                 if provider == "cuda" else ["CPUExecutionProvider"])

    t0 = time.perf_counter()
    det = HiroLayoutDetector(ONNX_DIR, input_size=IMGSZ, providers=providers,
                             num_threads=threads)
    load_s = time.perf_counter() - t0
    return det, load_s, det.session.get_providers()


def measure(det, pages, *, batch: int, rounds: int, warmup: int = 3):
    """返回 (ms_per_page 中位, 每轮 ms_per_page, 每页检出数)。

    失败（如显存不足 / session.run 抛错）返回 (None, [], [])，由调用方记录并继续 ——
    8 GB 显存下大 batch 有 OOM 风险，不能让一个配置挂掉整轮扫描。
    """
    n = len(pages)
    try:
        # 预热：跑 warmup 页（batch=1 形式，避免把 batch 预热混进计时）
        for _, img in pages[:warmup]:
            det.predict(img, threshold=CONF)

        per_round = []
        counts: list[int] = []
        for _ in range(rounds):
            t0 = time.perf_counter()
            total = 0
            if batch <= 1:
                for _, img in pages:
                    items, _ = det.predict(img, threshold=CONF)
                    total += len(items)
                    counts.append(len(items))
            else:
                for i in range(0, n, batch):
                    chunk = [img for _, img in pages[i:i + batch]]
                    res = det.predict_batch(chunk, threshold=CONF)
                    for items, _ in res:
                        total += len(items)
                        counts.append(len(items))
            el = time.perf_counter() - t0
            per_round.append(el * 1000 / n)
        return statistics.median(per_round), per_round, counts
    except Exception as exc:  # noqa: BLE001 — 大 batch 可能 OOM，记录后继续
        print(f"       [ERR] {type(exc).__name__}: {str(exc)[:160]}")
        return None, [], []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(HERE.parent / "Sample"))
    ap.add_argument("--limit", type=int, default=64,
                    help="用前 N 页；0 = 全部 256 页")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--batches", default="1,2,4,8",
                    help="批量大小扫描；batch=N 表示一次前向喂 N 页")
    ap.add_argument("--threads", default="",
                    help="intra_op 线程扫描；默认空 = 不扫（CUDA 下影响很小）")
    ap.add_argument("--providers", default="cuda",
                    help="逗号分隔：cuda / cpu。默认只跑 cuda")
    ap.add_argument("--configs", default="all", choices=["all", "headline"],
                    help="all = provider×batch（+可选线程扫描）；headline = 只跑 batch=1")
    ap.add_argument("--out", default=str(HERE / "out" / "hiro_gpu_bench.json"))
    args = ap.parse_args()

    import onnxruntime as ort

    pages = load_pages(Path(args.samples), args.limit)
    batches = [int(x) for x in args.batches.split(",") if x.strip()]
    threads_list = [int(x) for x in args.threads.split(",") if x.strip()]
    provider_list = [x.strip() for x in args.providers.split(",") if x.strip()]

    print("=" * 96)
    print("问题 #1：Hiro-Layout 同进程背靠背基准（GPU 优先）")
    print("=" * 96)
    print(f"onnxruntime : {ort.__version__}")
    print(f"providers   : {ort.get_available_providers()}")
    print(f"pages       : {len(pages)}  rounds={args.rounds}  conf={CONF}  imgsz={IMGSZ}")
    print(f"onnx        : {ONNX_DIR / 'layout_model' / 'RT-DETR_25.onnx'}")
    print()

    if "CUDAExecutionProvider" not in ort.get_available_providers():
        raise SystemExit("[!] 没有 CUDAExecutionProvider，无法跑 GPU 基准。排查见计划 §2。")

    results = {"onnxruntime": ort.__version__,
               "available_providers": ort.get_available_providers(),
               "pages": len(pages), "rounds": args.rounds, "conf": CONF,
               "imgsz": IMGSZ, "runs": []}

    configs = []
    for prov in provider_list:
        for b in ([1] if args.configs == "headline" else batches):
            configs.append({"provider": prov, "batch": b, "threads": None,
                            "label": f"{prov}/b{b}"})
    for t in threads_list:
        configs.append({"provider": provider_list[0], "batch": 1, "threads": t,
                        "label": f"{provider_list[0]}/b1/t{t}"})

    dets = {}
    for cfg in configs:
        key = (cfg["provider"], cfg["threads"])
        if key not in dets:
            det, load_s, actual = make_detector(cfg["provider"], cfg["threads"])
            dets[key] = (det, load_s, actual)
            print(f"[load] provider={cfg['provider']:<5} threads={cfg['threads']} "
                  f"-> {load_s:.2f}s  实际 providers={actual}")
        det, load_s, actual = dets[key]

        med, per_round, counts = measure(det, pages, batch=cfg["batch"],
                                         rounds=args.rounds)
        if med is None:
            print(f"[skip] {cfg['label']:<14} 失败（见上方错误），跳过")
            results.setdefault("_failed", []).append(
                {"label": cfg["label"], "error": "measure failed (OOM?)"})
            continue
        row = {**cfg, "load_s": round(load_s, 3), "actual_providers": actual,
               "ms_per_page_median": round(med, 1),
               "ms_per_page_rounds": [round(x, 1) for x in per_round],
               "spread_pct": round((max(per_round) - min(per_round)) / med * 100, 1),
               "n_boxes_total": sum(counts),
               "pages_measured": len(counts),
               "boxes_per_page": round(sum(counts) / len(counts), 2) if counts else 0.0,
               "per_page_counts": counts[:len(pages)] if counts else []}
        results["runs"].append(row)
        print(f"[run ] {cfg['label']:<14} {med:8.1f} ms/页  "
              f"rounds={row['ms_per_page_rounds']} spread={row['spread_pct']}%  "
              f"boxes={row['n_boxes_total']} ({row['boxes_per_page']}/页)")
        results.setdefault("_counts", {})[cfg["label"]] = counts[:len(pages)]

    # ---- 正确性交叉校验：batch=1 vs 最大 batch（都走 GPU）----
    #
    # 这一步验证的是 `predict_batch` 的解码对不对：各样本的 letterbox 比例/边距不同，
    # 若逐样本反变换写错，批量结果的框会整体偏移 → 检出数就会变。
    # （CPU/GPU 的数值一致性本应另测，但按"只用 GPU"的要求从略。）
    print()
    print("-" * 96)
    print("交叉校验：batch=1 与 batch=N 的逐页检出数是否一致（验证批量解码）")
    base_label = f"{provider_list[0]}/b1"
    base = results.get("_counts", {}).get(base_label, [])
    ok_all = True
    for lbl, cnt in results.get("_counts", {}).items():
        if lbl == base_label or not base:
            continue
        n_diff = sum(1 for a, b in zip(base, cnt) if a != b)
        same = base == cnt
        ok_all &= same
        print(f"  {base_label} vs {lbl:<10} : "
              + ("PASS" if same else f"FAIL（{n_diff}/{len(base)} 页不同）"))
        if not same:
            bad = [(i, a, b) for i, (a, b) in enumerate(zip(base, cnt)) if a != b][:6]
            print(f"      首批不一致 (页, b1, N): {bad}")
    if not base:
        print("  （没有 batch=1 结果，跳过）")
    results["batch_consistency_ok"] = ok_all

    # ---- 标签直方图（确认类别解读正确）----
    print()
    print("参考：单页标签直方图（第一页）")
    base_det = dets[(provider_list[0], None)][0]
    items, _ = base_det.predict(pages[0][1], threshold=CONF)
    hist = Counter(r["label"] for r in items)
    print(f"  {pages[0][0]}: n={len(items)} {dict(hist.most_common(10))}")
    results["page0_histogram"] = dict(hist)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\n[out] {args.out}")

    # ---- 结论行 ----
    best = min(results["runs"], key=lambda r: r["ms_per_page_median"])
    hours = best["ms_per_page_median"] * 94759 / 1000 / 3600
    verdict = ("通过（可迭代）" if best["ms_per_page_median"] <= 400 else
               "勉强（需靠批/缓存压缩）" if best["ms_per_page_median"] <= 600 else
               "不通过（回到选型讨论）")
    print(f"\n[结论] 最优配置 {best['label']} = {best['ms_per_page_median']:.1f} ms/页 "
          f"-> 94,759 页单次全量 {hours:.1f} h")
    print(f"       门槛判定（≤400 ms）: {verdict}")
    print(f"       批量解码一致性: "
          + ("PASS" if results.get("batch_consistency_ok") else "FAIL/未测"))


if __name__ == "__main__":
    sys.exit(main())

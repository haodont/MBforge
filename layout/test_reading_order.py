#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 `reading_order.py`，并测量它在真实专利页上的效果。

两部分：

**A. 等价性**（这是"照搬"的判据）
  从 `refs/Hiro-Smart-Doc/` 直接导入官方 `LayoutRunner`，用 `object.__new__` 绕过
  `__init__`（不加载权重 —— 那两个方法不依赖实例状态），逐输入比对：
  `determine_columns` 与 `column_sort` 的输出必须**完全一致**。
  覆盖：手工构造的 1/2/3 栏与跨栏标题用例 + 固定种子的随机模糊测试 + 全部真实页面。

  ⚠️ `refs/` 不在版本库里（见 `.gitignore`）。缺它时本脚本只跑 B 部分并明确提示。

**B. 质量**（这是"照搬是否有用"的判据）
  在真实页面上统计 **y 回跳**（下一框的 y0 明显小于当前框的 y0 = 回跳，即"该换栏却还在扫"）：
    · 各产物**存储顺序**（管线实际产出）
    · 同一批框再跑一次 column_sort（供对比）
  回跳是分栏未被处理的签名特征，纯光栅序不可能产生；但也不是越少越好 ——
  正常的"读完左栏换右栏"本身就是一次大回跳。

用法：
    python test_reading_order.py
    python test_reading_order.py --runs hiro_256_raworder hiro_256 baseline_256
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "Sample"
REFS = HERE.parent / "refs" / "Hiro-Smart-Doc"

sys.path.insert(0, str(HERE))

import reading_order as ro  # noqa: E402

# 回跳判据：下一个框的 y0 比当前框的 y0 小超过这么多（归一化页高）才算"回跳"
REGRESSION_MIN = 0.02


# ------------------------------------------------------------------ oracle

def load_oracle():
    """导入官方实现。返回 (runner, None) 或 (None, 原因)。"""
    if not REFS.is_dir():
        return None, f"refs/ 不存在: {REFS}（用 refs/README.md 的记录命令拉取）"
    sys.path.insert(0, str(REFS))
    try:
        from hiro_smart_doc.model_runners.layout import LayoutRunner
        return object.__new__(LayoutRunner), None   # 绕过 __init__，不需要权重
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


# ------------------------------------------------------------------ A 等价性

def make_cases():
    """手工构造用例：覆盖单栏 / 两栏 / 三栏 / 跨栏标题 / 框数不足。"""
    cases = []
    # 少于 3 个框
    cases.append([[[0.1, 0.1, 0.9, 0.2]], "1 框"])
    cases.append([[[0.1, 0.1, 0.4, 0.2], [0.6, 0.1, 0.9, 0.2]], "2 框"])
    # 单栏：所有框都靠左且够宽
    cases.append([[[0.05, 0.05 + i * 0.1, 0.45, 0.12 + i * 0.1] for i in range(7)],
                  "单栏"])
    # 两栏 + 跨栏标题
    boxes = [[0.05, 0.05, 0.45, 0.10], [0.55, 0.05, 0.95, 0.10],
             [0.05, 0.20, 0.45, 0.60], [0.55, 0.20, 0.95, 0.60],
             [0.05, 0.15, 0.95, 0.18],          # 跨栏标题
             [0.05, 0.65, 0.45, 0.90], [0.55, 0.65, 0.95, 0.90]]
    cases.append([boxes, "两栏+跨栏标题"])
    # 两栏，标题在中间（触发回灌）
    cases.append([[[0.05, 0.05, 0.45, 0.20], [0.55, 0.05, 0.95, 0.20],
                   [0.30, 0.25, 0.70, 0.30],
                   [0.05, 0.35, 0.45, 0.80], [0.55, 0.35, 0.95, 0.80]],
                  "两栏+居中标题"])
    # 三栏
    three = [[0.02 + c * 0.33, 0.10 + r * 0.15,
              0.28 + c * 0.33, 0.22 + r * 0.15]
             for c in range(3) for r in range(5)]
    cases.append([three, "三栏"])
    # 三栏 + 跨三栏标题
    cases.append([[[0.02, 0.05, 0.98, 0.09],
                   [0.02, 0.15, 0.30, 0.40], [0.35, 0.15, 0.63, 0.40], [0.68, 0.15, 0.96, 0.40],
                   [0.02, 0.45, 0.30, 0.85], [0.35, 0.45, 0.63, 0.85], [0.68, 0.45, 0.96, 0.85]],
                  "三栏+跨三栏标题"])
    return cases


def fuzz_cases(n=3000, seed=42):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        k = rng.randint(0, 14)
        boxes = []
        for _ in range(k):
            x0 = rng.random()
            x1 = min(1.0, x0 + rng.random() * 0.9)
            y0 = rng.random()
            y1 = min(1.0, y0 + rng.random() * 0.5)
            boxes.append([x0, y0, x1, y1])
        out.append((boxes, f"fuzz#{i}"))
    return out


def real_page_cases(runs):
    """从 detections.json 取真实页面的合并后区域，归一化。"""
    cases = []
    manifest = SAMPLE / "_pdf_samples.json"
    dims = {}
    if manifest.is_file():
        for m in json.loads(manifest.read_text(encoding="utf-8"))["added"]:
            dims[m["file"][:-4]] = (m["w"], m["h"])
    for run in runs:
        p = HERE / "out" / run / "detections.json"
        if not p.is_file():
            continue
        for pg in json.loads(p.read_text(encoding="utf-8"))["pages"]:
            wh = dims.get(pg["page"])
            if not wh:
                continue
            w, h = wh
            boxes = [[b[0] / w, b[1] / h, b[2] / w, b[3] / h]
                     for b in (r["bbox_px"] for r in pg["regions"])]
            cases.append((boxes, f"{run}/{pg['page']}"))
    return cases


def check_equivalence(oracle, cases, label):
    bad = 0
    for boxes, name in cases:
        a = [list(b) for b in boxes]
        b = [list(b) for b in boxes]
        mine_cols = ro.determine_columns(a)
        their_cols = oracle.determine_columns(b)
        if mine_cols != their_cols:
            bad += 1
            print(f"  ✗ determine_columns 不一致 [{name}] 我={mine_cols} 官方={their_cols}")
            continue
        mine = ro.sort_boxes([list(x) for x in boxes])
        theirs = oracle.column_sort([list(x) for x in boxes])
        if mine != theirs:
            bad += 1
            print(f"  ✗ column_sort 不一致 [{name}]")
            for i, (m, t) in enumerate(zip(mine, theirs)):
                if m != t:
                    print(f"      首个分歧 idx={i}: 我={m} 官方={t}")
                    break
            if len(mine) != len(theirs):
                print(f"      长度不同: 我={len(mine)} 官方={len(theirs)}")
    total = len(cases)
    print(f"  {label}: {total - bad}/{total} 一致" + ("  ✅" if bad == 0 else f"  ❌ {bad} 处不一致"))
    return bad


# ------------------------------------------------------------------ B 质量

def count_regressions(boxes):
    """返回 (回跳次数, 最大回跳幅度)。输入为最终顺序的归一化框。"""
    n, worst = 0, 0.0
    for prev, cur in zip(boxes, boxes[1:]):
        d = prev[1] - cur[1]
        if d > REGRESSION_MIN:
            n += 1
            worst = max(worst, d)
    return n, worst


def _col_of(b, ncols):
    """按官方阈值把框归到某一栏（仅用于度量，不参与排序）。"""
    if ncols == 1:
        return 1
    if ncols == 2:
        return 1 if b[0] < ro.SPAN_2COL_LEFT else 2
    if b[0] < ro.SPAN_3COL_LEFT:
        return 1
    return 2 if b[0] < ro.SPAN_3COL_MID else 3


def count_col_switches(boxes, ncols):
    """栏切换次数。

    比 y 回跳更贴切的度量：y 回跳分不清"正确地换到下一栏"（应当发生）与
    "错误地来回横跳"。而**一个正确的栏序（先读完第 1 栏再读第 2 栏…）只需要
    切换 (栏数 - 1) 次**；切换次数越多，说明栏被反复回访 = 交错。
    返回 (实际切换数, 理论下限)。
    """
    seq = [_col_of(b, ncols) for b in boxes]
    sw = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    return sw, max(0, len(set(seq)) - 1)


def quality_report(runs):
    """`runs`: [(产物目录名, 顺序口径)]，口径 ∈ {"stored", "column_sort"}。

    "stored" = 直接取 `detections.json` 里 regions 的存储顺序（即管线实际产出的顺序）；
    "column_sort" = 对同一批框重新跑一遍 column_sort（用于对比"若再排一次"）。
    """
    manifest = SAMPLE / "_pdf_samples.json"
    if not manifest.is_file():
        print("  缺 Sample/_pdf_samples.json，跳过")
        return
    dims = {m["file"][:-4]: (m["w"], m["h"])
            for m in json.loads(manifest.read_text(encoding="utf-8"))["added"]}

    print(f"{'产物 / 口径':<40}{'页数':>5}{'回跳总数':>9}"
          f"{'栏切换':>8}{'切换下限':>9}{'栏序超额页':>11}   栏数分布")
    for run, mode in runs:
        p = HERE / "out" / run / "detections.json"
        if not p.is_file():
            print(f"{run:<40}  （缺 {p.name}，跳过）")
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        n_pages = tot_reg = 0
        tot_sw = tot_sw_min = n_over = 0
        col_dist = {}
        for pg in data["pages"]:
            wh = dims.get(pg["page"])
            if not wh or not pg["regions"]:
                continue
            w, h = wh
            raw = [[r["bbox_px"][0] / w, r["bbox_px"][1] / h,
                    r["bbox_px"][2] / w, r["bbox_px"][3] / h] for r in pg["regions"]]
            seq = raw if mode == "stored" else ro.sort_boxes([list(b) for b in raw])
            cols = ro.determine_columns([list(b) for b in raw])
            col_dist[cols] = col_dist.get(cols, 0) + 1
            n, _ = count_regressions(seq)
            sw, sw_min = count_col_switches(seq, cols)
            n_pages += 1
            tot_reg += n
            tot_sw += sw
            tot_sw_min += sw_min
            if sw > sw_min:
                n_over += 1
        dist = " ".join(f"{k}栏×{v}" for k, v in sorted(col_dist.items()))
        print(f"{run + ' / ' + mode:<40}{n_pages:>5}{tot_reg:>9}"
              f"{tot_sw:>8}{tot_sw_min:>9}{n_over / max(1, n_pages):>11.1%}   {dist}")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["hiro_256", "baseline_256"])
    ap.add_argument("--no-fuzz", action="store_true")
    args = ap.parse_args()

    oracle, err = load_oracle()
    print("=" * 96)
    print("A. 与官方实现的等价性")
    print("=" * 96)
    if oracle is None:
        print(f"  ⚠️ 跳过：{err}")
    else:
        print(f"  oracle: {REFS}")
        bad = 0
        bad += check_equivalence(oracle, make_cases(), "手工用例")
        if not args.no_fuzz:
            bad += check_equivalence(oracle, fuzz_cases(), "随机模糊（3000 组）")
        bad += check_equivalence(oracle, real_page_cases(args.runs), "真实页面")
        print(f"\n  结论：{'完全等价 ✅' if bad == 0 else f'{bad} 处不一致 ❌'}")

    print()
    print("=" * 96)
    print("B. 真实页面上的效果（y 回跳 = 该换栏却还在扫，纯光栅序的签名特征）")
    print("=" * 96)
    print("  判据：下一框的 y0 比当前框的 y0 小超过 {:.2f} 页高，记一次回跳".format(REGRESSION_MIN))
    print()
    quality_report([(r, m) for r in args.runs for m in ("stored", "column_sort")])


if __name__ == "__main__":
    main()

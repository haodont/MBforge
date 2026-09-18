#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""阅读顺序：Hiro-Smart-Doc 的 column_sort 启发式（**忠实移植**）

## 为什么需要

Hiro 不输出阅读顺序 —— 区域列表的顺序就是模型前向的输出顺序，不是阅读序。
（对照：V3 的输出顺序**自带**逻辑阅读序，实测两栏页有 323 px 的 y 回跳。）

官方 Hiro-Smart-Doc 在后处理里用 `column_sort` + `determine_columns` 恢复顺序，
本模块是它的**逐行移植**，常量全部对应官方源码（`refs/Hiro-Smart-Doc/hiro_smart_doc/
model_runners/layout.py`，行号见各常量注释）。

## 坐标约定

一律**归一化 0..1、左上原点、y 向下** —— 与官方一致。
我们的 `bbox_px` 也是左上原点、y 向下，除以页面宽高即落到同一空间。

## 算法

1. 按 `y0` 全局排序（纯光栅序，只是起点）；
2. `determine_columns` 用「各栏内框高之和」判定 1 / 2 / 3 栏；
3. 按栏分发。**关键是跨栏框（标题行）的"回灌"**：遇到跨栏框时，把此刻已积累在
   右侧栏的框**全部灌回左栏**，于是标题排在它上方的正文之后、下方正文之前。
   这正是纯光栅排序做不到的 —— 也是这条启发式的全部价值。

## 阈值的来源与风险

全部是官方的魔法数字，**原样保留，不要随手调**。官方自己的注释也承认：

    # these magic numbers are based on case study and may need to be tuned

已实测的边界行为（见 `tests_reading_order.py`）：框数与栏宽分布决定成败，
对「整页单栏但左右各有一条窄边注」这类版式，`determine_columns` 可能误判成 2 栏。
"""

from __future__ import annotations

# ---- 常量：全部对应官方 layout.py 的字面量 -------------------------------------------
LINE1_SPLITTING = 0.33          # layout.py:84  第一/第二栏分界（归一化 x）
LINE2_SPLITTING = 0.60          # layout.py:84  第二/第三栏分界
MIN_BOXES_FOR_COLUMN_CHECK = 3  # layout.py:89  少于 3 个框直接判 1 栏
MIN_BAR_WIDTH = 0.1             # layout.py:95  太窄的框（行号/边注）不计入栏高
COL_HEIGHT_FLOOR = 0.2          # layout.py:98  栏高阈值下限
COL_HEIGHT_RATIO = 0.6          # layout.py:98  栏高阈值 = min(下限, 第一栏高 × 该比例)
SPAN_2COL_LEFT = 0.4            # layout.py:128 两栏：左半区判据
SPAN_2COL_RIGHT = 0.52          # layout.py:129 两栏：纯第一栏 vs 跨栏标题
SPAN_3COL_LEFT = 0.3            # layout.py:142 三栏：第 1 栏或跨栏
SPAN_3COL_MID = 0.6             # layout.py:158 三栏：第 2 栏或跨栏
SPAN_3COL_C1 = 0.4              # layout.py:143 三栏：纯第 1 栏
SPAN_3COL_C2 = 0.66             # layout.py:145 三栏：跨前两栏 vs 跨三栏
SPAN_3COL_C3 = 0.66             # layout.py:159 三栏：跨后两栏


def determine_columns(boxes, line1_splitting: float = LINE1_SPLITTING,
                      line2_splitting: float = LINE2_SPLITTING) -> int:
    """判定页面的栏数（1 / 2 / 3）。`boxes` 为归一化 [x0, y0, x1, y1]。

    判据不是「框落在哪一栏」，而是**各栏累计框高**：
    只有某栏真的堆了足够内容，才算存在该栏。这能避开"标题横跨中间"之类的情形。
    """
    if not boxes or len(boxes) < MIN_BOXES_FOR_COLUMN_CHECK:
        return 1

    column1_total_height = sum(
        abs(b[3] - b[1]) for b in boxes
        if b[0] < line1_splitting and b[2] - b[0] > MIN_BAR_WIDTH)
    column2_total_height = sum(
        abs(b[3] - b[1]) for b in boxes
        if line1_splitting < b[0] < line2_splitting and b[2] - b[0] > MIN_BAR_WIDTH)
    column3_total_height = sum(
        abs(b[3] - b[1]) for b in boxes
        if b[0] > line2_splitting and b[2] - b[0] > MIN_BAR_WIDTH)

    threshold = min(COL_HEIGHT_FLOOR, column1_total_height * COL_HEIGHT_RATIO)
    if column3_total_height > threshold:
        return 3
    if column2_total_height > threshold:
        return 2
    return 1


def sort_boxes(boxes):
    """按官方算法重排 `boxes`（**原地 sort，与官方一致**，并返回同一列表对象）。

    `boxes` 是归一化 [x0, y0, x1, y1] 的**可变**序列（list of list）。
    """
    boxes.sort(key=lambda b: b[1])          # 官方 layout.py:111 先按 y0 全局排序
    column_num = determine_columns(boxes)

    if column_num == 1:                     # 单栏：光栅序即阅读序
        return boxes

    col_1, col_2, col_3 = [], [], []

    if column_num == 2:
        for b in boxes:
            if b[0] < SPAN_2COL_LEFT:
                if b[2] < SPAN_2COL_RIGHT:
                    col_1.append(b)                        # 纯第一栏
                else:
                    col_2.append(b)                        # 跨栏标题行
                    col_1.extend(col_2)                    # ← 回灌
                    col_2 = []
            else:
                col_2.append(b)                            # 第二栏
        return col_1 + col_2

    for b in boxes:
        if b[0] < SPAN_3COL_LEFT:
            if b[2] < SPAN_3COL_C1:
                col_1.append(b)                            # 纯第一栏
            elif b[2] < SPAN_3COL_C2:
                col_2.append(b)                            # 跨前两栏
                col_1.extend(col_2)                        # ← 回灌
                col_2 = []
            else:
                col_3.append(b)                            # 跨三栏
                col_1.extend(col_2)                        # ← 回灌
                col_1.extend(col_3)
                col_2, col_3 = [], []
        elif b[0] < SPAN_3COL_MID:
            if b[2] > SPAN_3COL_C3:
                col_3.append(b)                            # 跨后两栏
                col_2.extend(col_3)                        # ← 回灌（灌进第二栏）
                col_3 = []
            else:
                col_2.append(b)                            # 纯第二栏
        else:
            col_3.append(b)                                # 第三栏
    return col_1 + col_2 + col_3


def assign(regions, page):
    """对**合并后**的最终区域集重排顺序，并把新下标写回 `reading_order`。

    返回重排后的新列表（不改动传入列表本身）。`region["reading_order"]` 会被就地更新。

    ⚠️ 只在最终集合上调用一次。合并规则 R1–R5 会删改区域，
    在它之前盖的 `reading_order` 会失效。
    """
    if not regions:
        return list(regions)

    w = float(page["width_px"])
    h = float(page["height_px"])

    work = []                                  # (归一化四元组, 原 region)
    for r in regions:
        x0, y0, x1, y1 = (float(v) for v in r["bbox_px"])
        work.append(([x0 / w, y0 / h, x1 / w, y1 / h], r))

    sorted_norm = sort_boxes([b for b, _ in work])

    # 归一化四元组可能重复，故按 id 取回原始 region，避免值相等时配错
    by_norm = {}
    for b, r in work:
        by_norm.setdefault(tuple(b), []).append(r)
    out = []
    for b in sorted_norm:
        out.append(by_norm[tuple(b)].pop(0))

    for idx, r in enumerate(out):
        r["reading_order"] = idx
    return out

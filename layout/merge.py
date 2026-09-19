#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
版面识别内部的区域合并去重。

输入是检测器的区域列表与 MolDet 的分子框列表（同一张 144 DPI 图、同一坐标系），
输出是统一的 `Region` 列表（DESIGN.md §3.2）。

五条规则，按执行顺序：

  R1  检测器内部同类去重    —— 同类且 IoU > 0.7 的重复框，保留高分者               （实测 5/32 页有此问题）
  R2  检测器内部内嵌抑制    —— 文本流子块（area<1%父块 且被父块包含>0.8）降级为父块 span
  R3  跨模型 1:1 让位        —— image/chart 区域与分子框 IoU>0.7 → 该区域改为 molecule
  R4  跨模型 1:N 容器        —— image/chart 区域包含多个分子框 → 保留为容器，分子挂为 children
  R5  文本框去重叠          —— 同为文本的框两两求交，有交集即并集合并

R4 是 R3 的必要补全：实测一个 `image` 区域里装着 **16 个**分子，
若整块让位成一个 molecule，会把"16 个分子的合成路线"误标为"1 个分子"。故按 1:1 / 1:N 分治。

⚠️ R2 不得吞掉分子框——分子框虽然也被 image 包含，但那属 R3/R4 的职责。
"""

from __future__ import annotations

# 可作为内联内容被父级 text 块吞掉的类型
# 刻意不含 "text" 本身：小 text 块可能是合法独立块（如表格标题、独立标注），
# 不该被父级大文本块吞掉。同类重叠交给 R1 去重。
#
# ⚠️ 这几组集合按 **label** 匹配，因此是 **PP-DocLayoutV3 的词表**。
#    换检测器时由调用方通过 params 覆盖——见 hiro.HIRO_MERGE_LABELS。
_INLINE_CHILD = {"formula", "formula_number", "figure_title",
                 "footnote", "vision_footnote", "reference", "reference_content"}
# R2 的父块词表：只有这些"正文块"才允许吞并内联子块
_R2_PARENT_LABELS = {"text", "content", "paragraph_title"}
# R5 的适用范围 = **下游会当作文本消费的全部 label**，即 `v3.REGION_TYPE_CATEGORY`
# 里类别为 `text` 的那些 RegionType 所对应的 label。
#
# ⚠️ 这组集合必须覆盖**全部会被下游当作文本的 label**：实测第 400 页存在两个
# **bbox 完全相同、label 不同** 的区域（`figure_title` 与 `text`，都是
# (125.5,1012.2,1064.5,1145.4)）。下游按 RegionType 取输入，两者都算 text，
# 于是同一块被裁两次、里面每一行被识别两遍（实测 220 行重复、占 7.3%）。
# → `figure_title` 必须在内。
_TEXTY = {"text", "title", "formula", "paragraph_title", "content", "abstract",
          "algorithm", "aside_text", "footnote", "vision_footnote",
          "reference", "reference_content", "figure_title", "formula_number"}
# 容器型 **RegionType**（可包含分子）。
#
# ⚠️ 按 type 匹配而非 label：V3 的 label 与 type 在 image/chart 上一一对应；
#    而 Hiro 把结构式判成 `chem`/`draw`/`figcx`/`struc` 等 label，它们的 type 才是 `image`。
#    按 label 匹配会让 Hiro 的图像区域被 R3/R4 完全忽略
#    （实测 256 页：Hiro 产出 775 个 image 区域，R3/R4 命中数为 0，685 个分子全部
#    沦为 standalone，分子↔图容器关系彻底丢失）。
_CONTAINER_TYPES = {"image", "chart"}

# 分子区域的 `kind`。**改 type 时必须一起改 kind**：下游（MBForge 的
# `evidence_join._join_evidence_dedupe`）按 `kind` 仲裁 molecule 与 image_region，
# 只改 type 会让让位后的分子仍被当作图片处理。
_MOLECULE_KIND = "molecule"

DEFAULTS = dict(
    iou_dup=0.7,          # R1 同类去重阈值
    contain_ratio=0.8,    # 包含判定的覆盖率阈值（R2/R3/R4）
    child_area_ratio=0.01,  # R2：子块面积 / 父块面积 上限
    iou_yield=0.7,        # R3：让位阈值
    contain_ratio_text=0.95,  # R5：text 类框被判为"被包含"的覆盖率阈值
    cross_module=True,    # False = 跳过 R3/R4，把分子扁平输出，交给 MBForge 仲裁
    # ↓ 词表相关，None = 用上面的 V3 默认值；换检测器时覆盖
    texty_labels=None,
    inline_child_labels=None,
    r2_parent_labels=None,
)


# ------------------------------------------------------------------ 几何

def _bbox(r):
    return r["bbox_px"]


def iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def coverage(inner, outer) -> float:
    """inner 被 outer 覆盖的面积比例。"""
    a = area(inner)
    if a <= 0:
        return 0.0
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    return inter / a


def inter_area(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def union_box(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def px_box_to_pdf(box, page_height_pt: float, px_per_pt: float):
    """像素框 → PDF pt（左下原点，y 向上）。与 v3.py 的同名函数一致。

    ⚠️ y0/y1 必须交换——逐坐标套用 `page_height_pt - y/px_per_pt` 会得到倒置框且不报错。
    """
    x0, y0, x1, y1 = box
    return (x0 / px_per_pt,
            page_height_pt - y1 / px_per_pt,
            x1 / px_per_pt,
            page_height_pt - y0 / px_per_pt)


# ------------------------------------------------------------------ 合并

def merge(det_regions, molecules, doc_id: str, page_num: int,
          page_height_pt: float, px_per_pt: float, params: dict | None = None):
    """返回 (regions, stats)。regions 为合并后的统一 Region 列表，已重编号且按阅读序排列。

    `det_regions` 是**任一面检测器**（V3 或 Hiro）的原始区域列表——本函数两个检测器共用。
    """
    p = {**DEFAULTS, **(params or {})}
    texty_labels = p["texty_labels"] or _TEXTY
    inline_child = p["inline_child_labels"] or _INLINE_CHILD
    r2_parent_labels = p["r2_parent_labels"] or _R2_PARENT_LABELS
    stats = {"r1_dup_removed": 0, "r2_suppressed": 0, "r5_text_merged": 0,
             "r3_yielded": 0, "r4_containers": 0, "r4_children": 0,
             "molecules_standalone": 0}

    # 深拷贝，避免改动调用方数据。
    # ⚠️ `source` 必须沿用输入（`layout_v3` / `layout_hiro`），不能在这里写死 ——
    # 写死会让 Hiro 产出的区域全部被标成 V3。
    regs = [{**r, "children": [], "meta": {}} for r in det_regions]

    # ---------- R1：同类重复框去重 ----------
    drop = set()
    for i in range(len(regs)):
        if i in drop:
            continue
        for j in range(i + 1, len(regs)):
            if j in drop or regs[i]["label"] != regs[j]["label"]:
                continue
            if iou(_bbox(regs[i]), _bbox(regs[j])) > p["iou_dup"]:
                loser = j if regs[i]["score"] >= regs[j]["score"] else i
                keep = i if loser == j else j
                drop.add(loser)
                regs[keep].setdefault("meta", {}).setdefault("merged_from", []).append(
                    {"reason": "dup", "n": 1, "label": regs[loser]["label"],
                     "score": regs[loser]["score"], "bbox_px": regs[loser]["bbox_px"]})
                regs[keep]["source"] = "merged"
                stats["r1_dup_removed"] += 1
    regs = [r for k, r in enumerate(regs) if k not in drop]

    # ---------- R2：文本流内嵌抑制 ----------
    suppress = set()
    for i, child in enumerate(regs):
        if child["label"] not in inline_child:
            continue
        cb = _bbox(child)
        ca = area(cb)
        if ca <= 0:
            continue
        for j, parent in enumerate(regs):
            if i == j or parent["type"] != "text":
                continue
            if parent["label"] not in r2_parent_labels:
                continue
            pb = _bbox(parent)
            pa = area(pb)
            if pa <= 0 or ca >= pa * p["child_area_ratio"]:
                continue
            if coverage(cb, pb) > p["contain_ratio"]:
                suppress.add(i)
                parent.setdefault("meta", {}).setdefault("spans", []).append(
                    {"label": child["label"], "score": child["score"],
                     "bbox_px": child["bbox_px"]})
                parent["source"] = "merged"
                stats["r2_suppressed"] += 1
                break
    regs = [r for k, r in enumerate(regs) if k not in suppress]

    # ---------- R5：text 类框去重叠（有交集即并集合并） ----------
    # 实测（100 页）检测器的 text/title/formula 框共 6605 个两两组合，288 对（4.4%）有重叠，
    # 分两种形态：
    #   (a) 小框被大框完全包含 —— 248 对，交集/较小框 = 1.000
    #   (b) 部分重叠           —— 其余
    # 两种都会让下游把同一段文字识别两遍。只挡 (a) 不够：实测挡完 (a) 之后，
    # 剩余的 (b) 仍产生 **238 行重复（占 7.8%）**。
    # 故统一处理：**有交集就并成并集框**（union-find 分组），使一段文字只落进一个块。
    idx_texty = [i for i, r in enumerate(regs) if r["label"] in texty_labels]
    if len(idx_texty) > 1:
        parent = {i: i for i in idx_texty}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a_i in range(len(idx_texty)):
            for b_i in range(a_i + 1, len(idx_texty)):
                i, j = idx_texty[a_i], idx_texty[b_i]
                if inter_area(_bbox(regs[i]), _bbox(regs[j])) > 0:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[max(ri, rj)] = min(ri, rj)

        groups: dict[int, list[int]] = {}
        for i in idx_texty:
            groups.setdefault(find(i), []).append(i)

        drop5 = []
        for members in groups.values():
            if len(members) == 1:
                continue
            members.sort(key=lambda k: -regs[k]["score"])   # 最高分的当代表
            rep = regs[members[0]]
            box = _bbox(regs[members[0]])
            for k in members[1:]:
                box = union_box(box, _bbox(regs[k]))
                drop5.append(k)
                rep.setdefault("meta", {}).setdefault("merged_text", []).append(
                    {"label": regs[k]["label"], "score": regs[k]["score"],
                     "bbox_px": regs[k]["bbox_px"]})
            rep["bbox_px"] = [round(v, 2) for v in box]
            rep["bbox_pdf"] = [round(v, 2) for v in
                               px_box_to_pdf(box, page_height_pt, px_per_pt)]
            rep["source"] = "merged"
            stats["r5_text_merged"] += len(members) - 1
        if drop5:
            dset = set(drop5)
            regs = [r for k, r in enumerate(regs) if k not in dset]

    # ---------- R3 / R4：跨模块合并 ----------
    # ``cross_module=False`` 时整段跳过：molecule ↔ image_region 的几何仲裁
    # **交由 MBForge 的 `_join_evidence_dedupe` 决定**（其规则更激进：跨 kind IoU>0
    # 即丢弃、molecule 恒赢 image_region）。本模块只做 MBForge 没有的 R1/R2。
    containers = ([r for r in regs if r["type"] in _CONTAINER_TYPES]
                  if p["cross_module"] else [])
    used_mol = set()
    for r in containers:
        rb = _bbox(r)
        # k not in used_mol：避免一个分子被两个重叠容器重复收纳（实测会多算）
        inside = [k for k, m in enumerate(molecules)
                  if k not in used_mol
                  and coverage(m["bbox_px"], rb) > p["contain_ratio"]]
        if not inside:
            continue
        # 1:1 —— 分子框与区域框基本重合 → 整块让位
        if len(inside) == 1 and iou(molecules[inside[0]]["bbox_px"], rb) > p["iou_yield"]:
            m = molecules[inside[0]]
            used_mol.add(inside[0])
            r["type"] = "molecule"
            r["label"] = "molecule"
            r["kind"] = _MOLECULE_KIND   # kind 必须跟着 type 一起改，下游按 kind 仲裁
            r["score"] = m["score"]
            r["bbox_px"] = list(m["bbox_px"])
            r["bbox_pdf"] = list(m["bbox_pdf"])
            # 保留 V3 的多边形作裁剪依据（§7 规则 2）
            r.setdefault("meta", {})["container_polygon_px"] = r.get("polygon_px")
            r["source"] = "merged"
            r["meta"]["merged_from"] = ["layout_v3", "molecule_det"]
            stats["r3_yielded"] += 1
            continue
        # 1:N —— 保留为容器，分子挂 children
        kids = []
        for k in sorted(inside, key=lambda k: (molecules[k]["bbox_px"][1],
                                               molecules[k]["bbox_px"][0])):
            m = molecules[k]
            used_mol.add(k)
            kids.append({
                "region_id": m["region_id"],
                "type": "molecule", "label": "molecule", "kind": _MOLECULE_KIND,
                "score": m["score"],
                "source": m["source"], "reading_order": len(kids),
                "bbox_px": list(m["bbox_px"]), "bbox_pdf": list(m["bbox_pdf"]),
                "polygon_px": [], "polygon_pdf": [],
                "content": None, "children": [], "meta": {},
            })
        r["children"] = kids
        r["source"] = "merged"
        r.setdefault("meta", {})["container"] = True
        r["meta"]["molecule_count"] = len(kids)
        stats["r4_containers"] += 1
        stats["r4_children"] += len(kids)

    # 未被任何容器吸收的分子 → 独立 molecule 区域
    for k, m in enumerate(molecules):
        if k in used_mol:
            continue
        stats["molecules_standalone"] += 1
        regs.append({
            "region_id": m["region_id"],
            "type": "molecule", "label": "molecule", "kind": _MOLECULE_KIND,
            "score": m["score"],
            "source": "molecule_det", "reading_order": None,
            "bbox_px": list(m["bbox_px"]), "bbox_pdf": list(m["bbox_pdf"]),
            "polygon_px": [], "polygon_pdf": [],
            "content": None, "children": [], "meta": {},
        })

    # ---------- 重编号 + 阅读序 ----------
    # 顶层按 V3 原阅读序；独立分子按位置插在末尾
    regs.sort(key=lambda r: (0 if r["source"] != "molecule_det" else 1,
                             r.get("reading_order") or 0,
                             r["bbox_px"][1]))
    for seq, r in enumerate(regs):
        r["reading_order"] = seq
        n_children = len(r["children"])
        r["region_id"] = f"{doc_id}-{page_num}-{r['type']}-{seq}" + (
            f"({n_children}mol)" if n_children else "")
        for cseq, c in enumerate(r["children"]):
            c["region_id"] = f"{r['region_id']}.mol{cseq}"
            c["reading_order"] = cseq

    return regs, stats


def flatten(regions):
    """把容器展开成扁平列表（容器 + 其 children），供渲染与统计。"""
    out = []
    for r in regions:
        out.append(r)
        out.extend(r["children"])
    return out

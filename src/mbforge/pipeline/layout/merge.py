"""Intra-detector region de-duplication (R1 / R2 / R5).

Three rules, applied in order:

  R1  same-label duplicate boxes      — keep the higher-scoring box     (IoU > 0.7)
  R2  inline child suppression        — a text-stream sub-block is demoted to a span
  R5  text-box overlap merging        — any two text boxes that intersect are unioned

The source project's R3/R4 (**cross-model** arbitration between a layout region
and a molecule box) are deliberately **not** ported: in MBForge that arbitration
belongs to ``pipeline.artifacts.evidence_join._join_evidence_dedupe``, which
already implements it by *category* (molecule always wins over image) and is
more aggressive than R3/R4. Re-implementing it here would duplicate the rule.

⚠️ R2/R5 match by **label**, so their wordlists are detector-specific. The
defaults below are Hiro's; a different detector must override them through
``params`` or its R2/R5 hits silently drop to zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .regions import px_box_to_pdf

#: R5 scope = every label the text-recognition step will consume as text.
#:
#: This set must cover **all** labels that are read as text downstream. The
#: source project measured duplicate reads caused by two regions with identical
#: bboxes but different labels (``figure_title`` vs ``text``) — 220 duplicate
#: lines, 7.3% of the page. Missing a text-ish label here reintroduces that.
HIRO_TEXTY_LABELS: frozenset[str] = frozenset(
    {
        "text",
        "title",
        "sec",
        "mnote",
        "cap",
        "figno",
        "lineno",
        "colno",
        "ref",
        "toc",
        "bib",
        "srep",
        "eqn",
    }
)

#: R2: labels allowed to be swallowed by a parent text block.
HIRO_INLINE_CHILD_LABELS: frozenset[str] = frozenset(
    {"eqn", "figno", "lineno", "colno", "cap", "mnote", "ref", "toc"}
)

#: R2 parent labels: only these "body" blocks may swallow inline children.
HIRO_R2_PARENT_LABELS: frozenset[str] = frozenset({"text", "sec", "title"})

#: Merge tuning. All thresholds are the source project's measured values.
DEFAULTS: dict[str, Any] = {
    "iou_dup": 0.7,  # R1 same-label duplicate threshold
    "contain_ratio": 0.8,  # containment coverage threshold (R2)
    "child_area_ratio": 0.01,  # R2: child area / parent area upper bound
    "texty_labels": None,  # None = HIRO_TEXTY_LABELS
    "inline_child_labels": None,  # None = HIRO_INLINE_CHILD_LABELS
    "r2_parent_labels": None,  # None = HIRO_R2_PARENT_LABELS
}


def bbox_area(box: Sequence[float]) -> float:
    return max(0.0, float(box[2]) - float(box[0])) * max(
        0.0, float(box[3]) - float(box[1])
    )


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def coverage(inner: Sequence[float], outer: Sequence[float]) -> float:
    """Fraction of *inner*'s area covered by *outer*."""
    area = bbox_area(inner)
    if area <= 0:
        return 0.0
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    return inter / area


def intersection_area(a: Sequence[float], b: Sequence[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def union_box(
    a: Sequence[float], b: Sequence[float]
) -> tuple[float, float, float, float]:
    return (
        min(a[0], b[0]),
        min(a[1], b[1]),
        max(a[2], b[2]),
        max(a[3], b[3]),
    )


def merge(
    regions: Sequence[dict[str, Any]],
    *,
    page_height_pt: float,
    px_per_pt: float,
    params: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply R1/R2/R5 and renumber the surviving regions.

    Returns ``(regions, stats)``. The result preserves input order; the reading
    order is (re)assigned afterwards on this final set by
    :func:`mbforge.pipeline.layout.reading_order.assign`.
    """
    config = {**DEFAULTS, **(params or {})}
    texty_labels = config["texty_labels"] or HIRO_TEXTY_LABELS
    inline_child = config["inline_child_labels"] or HIRO_INLINE_CHILD_LABELS
    r2_parent_labels = config["r2_parent_labels"] or HIRO_R2_PARENT_LABELS

    stats = {"r1_dup_removed": 0, "r2_suppressed": 0, "r5_text_merged": 0}

    # Shallow-copy each region: R5 mutates bbox in place on the survivors.
    regs = [dict(region, meta=dict(region.get("meta") or {})) for region in regions]

    # ---------- R1: same-label duplicate boxes ----------
    dropped: set[int] = set()
    for i in range(len(regs)):
        if i in dropped:
            continue
        for j in range(i + 1, len(regs)):
            if j in dropped or regs[i]["label"] != regs[j]["label"]:
                continue
            if bbox_iou(regs[i]["bbox_px"], regs[j]["bbox_px"]) > config["iou_dup"]:
                loser = j if regs[i]["score"] >= regs[j]["score"] else i
                keep = i if loser == j else j
                dropped.add(loser)
                regs[keep]["meta"].setdefault("merged_from", []).append(
                    {
                        "reason": "dup",
                        "label": regs[loser]["label"],
                        "score": regs[loser]["score"],
                        "bbox_px": regs[loser]["bbox_px"],
                    }
                )
                regs[keep]["source"] = "merged"
                stats["r1_dup_removed"] += 1
    regs = [region for index, region in enumerate(regs) if index not in dropped]

    # ---------- R2: inline child suppression ----------
    suppressed: set[int] = set()
    for i, child in enumerate(regs):
        if child["label"] not in inline_child:
            continue
        child_box = child["bbox_px"]
        child_area = bbox_area(child_box)
        if child_area <= 0:
            continue
        for j, parent in enumerate(regs):
            if i == j or parent["type"] != "text":
                continue
            if parent["label"] not in r2_parent_labels:
                continue
            parent_area = bbox_area(parent["bbox_px"])
            if (
                parent_area <= 0
                or child_area >= parent_area * config["child_area_ratio"]
            ):
                continue
            if coverage(child_box, parent["bbox_px"]) > config["contain_ratio"]:
                suppressed.add(i)
                parent["meta"].setdefault("spans", []).append(
                    {
                        "label": child["label"],
                        "score": child["score"],
                        "bbox_px": child["bbox_px"],
                    }
                )
                parent["source"] = "merged"
                stats["r2_suppressed"] += 1
                break
    regs = [region for index, region in enumerate(regs) if index not in suppressed]

    # ---------- R5: text-box overlap merging ----------
    # The source project measured 288 overlapping pairs among 6605 text boxes on
    # 100 pages (4.4%), in two shapes: full containment (248 pairs) and partial
    # overlap. Handling only containment still left 238 duplicate lines (7.8%),
    # so any intersection merges — union-find grouping, highest score wins.
    texty_indexes = [
        index for index, region in enumerate(regs) if region["label"] in texty_labels
    ]
    if len(texty_indexes) > 1:
        parent = {index: index for index in texty_indexes}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a_pos in range(len(texty_indexes)):
            for b_pos in range(a_pos + 1, len(texty_indexes)):
                i, j = texty_indexes[a_pos], texty_indexes[b_pos]
                if intersection_area(regs[i]["bbox_px"], regs[j]["bbox_px"]) > 0:
                    root_i, root_j = find(i), find(j)
                    if root_i != root_j:
                        parent[max(root_i, root_j)] = min(root_i, root_j)

        groups: dict[int, list[int]] = {}
        for index in texty_indexes:
            groups.setdefault(find(index), []).append(index)

        dropped_r5: list[int] = []
        for members in groups.values():
            if len(members) == 1:
                continue
            members.sort(key=lambda index: -regs[index]["score"])
            representative = regs[members[0]]
            box = tuple(float(value) for value in regs[members[0]]["bbox_px"])
            for index in members[1:]:
                box = union_box(box, regs[index]["bbox_px"])
                dropped_r5.append(index)
                representative["meta"].setdefault("merged_text", []).append(
                    {
                        "label": regs[index]["label"],
                        "score": regs[index]["score"],
                        "bbox_px": regs[index]["bbox_px"],
                    }
                )
            representative["bbox_px"] = [round(value, 2) for value in box]
            representative["bbox_pdf"] = [
                round(value, 2)
                for value in px_box_to_pdf(box, page_height_pt, px_per_pt)
            ]
            representative["source"] = "merged"
            stats["r5_text_merged"] += len(members) - 1
        if dropped_r5:
            drop_set = set(dropped_r5)
            regs = [
                region for index, region in enumerate(regs) if index not in drop_set
            ]

    # ---------- renumber ----------
    for seq, region in enumerate(regs):
        region["reading_order"] = seq
        region["region_id"] = (
            f"{region['doc_id']}-{region['page']}-{region['type']}-{seq}"
        )

    return regs, stats


__all__ = [
    "DEFAULTS",
    "HIRO_INLINE_CHILD_LABELS",
    "HIRO_R2_PARENT_LABELS",
    "HIRO_TEXTY_LABELS",
    "bbox_area",
    "bbox_iou",
    "coverage",
    "merge",
    "union_box",
]

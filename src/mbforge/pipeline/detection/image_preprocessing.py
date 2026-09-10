"""Molecule image preprocessing — applied between YOLO crop and MolParser.

Pipeline (grayscale in, grayscale out — no binarization):
1. Ink mask on the grayscale crop (pixel < 200)
2. DBSCAN-cluster the foreground ink pixels (eps=8, min_samples=15)
3. Keep the largest cluster (the molecular drawing); everything else
   (adjacent text labels, table fragments, specks) becomes ``others``

``main``/``others`` keep their original gray values: MolParser handles
antialiased strokes better than the hard 0/255 flattening we used before,
and the ink *definition* (<200) that drives the DBSCAN split is unchanged.

This improves MolParser accuracy on real-world patent figures where the
crop box often captures adjacent text fragments and tables. Clustering runs
on ink *pixels*, not component centroids: at 200 DPI a molecule's own atom
letters sit 20-50 px apart from each other, so centroid clustering split the
structure into fragments and discarded 70-95% of the foreground from
``main`` (measured on WO2026037254A1 crops).

The same split drives the crop-label OCR input. The caller hands in the wider
window B — A extended **only to the right and below**, so both share a
top-left origin and B's overlapping region is pixel-identical to A — and
:func:`erase_ink_region` whites out the ``main`` mask. What remains is
``others`` plus whatever characters the extension pulled in, with the
molecular drawing removed so the text detector is not drawn to the
structure's own atom labels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

try:
    from sklearn.cluster import DBSCAN

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

# 输入 DBSCAN 的墨迹像素上限：超过则跳过聚类，返回未拆分的灰度图。
# sklearn DBSCAN 在 2D 上 O(n log n)，30k 点内毫秒级；更大的墨迹面积
# 只会出现在异常稠密的整页扫描上，此时不拆分退回原 crop 是安全行为。
_DBSCAN_MAX_POINTS = 30_000


def _largest_ink_cluster_mask(
    arr: np.ndarray,
    eps: float = 8.0,
    min_samples: int = 15,
) -> np.ndarray | None:
    """DBSCAN the foreground ink pixels, return the largest cluster as a mask.

    arr: grayscale image (uint8); ink = pixel < 200

    Returns a boolean mask (same shape as ``arr``) covering the DBSCAN
    cluster with the most ink pixels, or ``None`` when clustering is not
    applicable (sklearn missing, no foreground, over the point cap, or no
    non-noise cluster formed).
    """
    if not _SKLEARN_AVAILABLE:
        return None

    ys, xs = np.nonzero(arr < 200)
    n = ys.size
    if n == 0:
        return None

    if n > _DBSCAN_MAX_POINTS:
        # ponytail: stride-subsample instead of assigning every pixel via
        # KD-tree nearest-label; dense crops beyond the cap degrade to
        # nearest-sampled-label holes being visually irrelevant anyway.
        stride = int(np.ceil(n / _DBSCAN_MAX_POINTS))
        ys, xs = ys[::stride], xs[::stride]

    coords = np.column_stack([ys, xs]).astype(np.float32)
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit(coords).labels_

    counts: dict[int, int] = {}
    for lbl in labels:
        if lbl == -1:
            continue
        counts[int(lbl)] = counts.get(int(lbl), 0) + 1
    if not counts:
        return None
    largest = max(counts, key=counts.get)

    keep = labels == largest
    mask = np.zeros(arr.shape, dtype=bool)
    mask[ys[keep], xs[keep]] = True
    return mask


@dataclass(frozen=True)
class MoleculeSplit:
    """One molecule crop split into its drawing, its offcut, and the mask.

    ``main`` / ``others`` are what :func:`preprocess_mol_image` returns;
    ``main_mask`` is the largest-cluster mask over the *input* crop that
    produced them, so a caller can blank the drawing out of a wider window
    sharing this crop's top-left origin.
    """

    main: Image.Image
    others: Image.Image | None
    main_mask: np.ndarray | None


def split_molecule_crop(
    img: Image.Image,
    dbscan_eps: float = 8.0,
    dbscan_min_samples: int = 15,
    padding_px: int = 8,
) -> MoleculeSplit:
    """Split a molecule crop into the drawing, the offcut, and the mask.

    - ``main``: a new PIL Image (mode L) containing only the largest ink
      cluster (the molecular drawing), tightly cropped with padding; original
      gray values are preserved.
    - ``others``: the remaining foreground (text labels, fragments, noise) on
      a white background, ``None`` when there is nothing to separate.
    - ``main_mask``: the largest-cluster mask over ``img``; ``None`` when
      clustering could not run (no sklearn, no foreground, over the point
      cap) or no non-noise cluster formed.
    """
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    ink = gray < 200

    main_mask = _largest_ink_cluster_mask(
        gray, eps=dbscan_eps, min_samples=dbscan_min_samples
    )
    if main_mask is None or not main_mask.any():
        return MoleculeSplit(Image.fromarray(gray, mode="L"), None, None)

    ys, xs = np.where(main_mask)
    y0 = max(int(ys.min()) - padding_px, 0)
    y1 = min(int(ys.max()) + padding_px, gray.shape[0])
    x0 = max(int(xs.min()) - padding_px, 0)
    x1 = min(int(xs.max()) + padding_px, gray.shape[1])

    main = Image.fromarray(gray[y0:y1, x0:x1], mode="L")

    # Off-cluster foreground (labels / fragments) cropped to its own tight
    # box, so labels outside the structure bbox survive for OCR. Original
    # gray values are kept; only the background is forced to white.
    others_mask = ink & ~main_mask
    if not others_mask.any():
        others = None
    else:
        oy, ox = np.where(others_mask)
        oy0 = max(int(oy.min()) - padding_px, 0)
        oy1 = min(int(oy.max()) + padding_px, gray.shape[0])
        ox0 = max(int(ox.min()) - padding_px, 0)
        ox1 = min(int(ox.max()) + padding_px, gray.shape[1])
        other = np.full((oy1 - oy0, ox1 - ox0), 255, dtype=np.uint8)
        other[others_mask[oy0:oy1, ox0:ox1]] = gray[oy0:oy1, ox0:ox1][
            others_mask[oy0:oy1, ox0:ox1]
        ]
        others = Image.fromarray(other, mode="L")
    return MoleculeSplit(main, others, main_mask)


def preprocess_mol_image(
    img: Image.Image,
    dbscan_eps: float = 8.0,
    dbscan_min_samples: int = 15,
    padding_px: int = 8,
) -> tuple[Image.Image, Image.Image | None]:
    """Preprocess a molecule crop for MolParser.

    Returns ``(main, others)`` — see :func:`split_molecule_crop`, which owns
    the split logic and additionally exposes the mask.
    """
    split = split_molecule_crop(img, dbscan_eps, dbscan_min_samples, padding_px)
    return split.main, split.others


def erase_ink_region(image: Image.Image, mask: np.ndarray) -> Image.Image:
    """Return ``image`` with the ``mask`` pixels painted white.

    ``mask`` is top-left anchored and may be smaller than ``image``: the
    mask comes from the tight crop A while ``image`` is the wider window B
    (A extended right and below), and the two share a top-left corner, so
    no coordinate translation is needed.
    """
    gray = np.asarray(image.convert("L"), dtype=np.uint8).copy()
    height = min(int(mask.shape[0]), gray.shape[0])
    width = min(int(mask.shape[1]), gray.shape[1])
    if height and width:
        gray[:height, :width][mask[:height, :width]] = 255
    return Image.fromarray(gray, mode="L")

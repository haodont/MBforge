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
from typing import Any

import numpy as np
from PIL import Image

# Torch is loaded lazily so CPU-only installs can still start the API and use
# the documented unsplit-crop fallback. The active development environment
# installs Torch through the ``gpu`` extra.
_TORCH_AVAILABLE: bool | None = None


def _get_torch() -> Any | None:
    """Return Torch when importable, caching an optional-dependency failure."""
    global _TORCH_AVAILABLE
    if _TORCH_AVAILABLE is False:
        return None
    try:
        import torch
    except (ImportError, OSError, RuntimeError):
        _TORCH_AVAILABLE = False
        return None
    _TORCH_AVAILABLE = True
    return torch


# 输入 DBSCAN 的墨迹像素上限：超过则跳过聚类，返回未拆分的灰度图。
# Torch DBSCAN uses a spatial grid, so neighborhood checks stay local instead
# of materializing an O(n²) distance matrix. Larger ink areas only occur in
# unusually dense crops; subsampling them preserves the safe fallback.
_DBSCAN_MAX_POINTS = 30_000


def _largest_ink_cluster_mask(
    arr: np.ndarray,
    eps: float = 8.0,
    min_samples: int = 15,
) -> np.ndarray | None:
    """Run Torch DBSCAN on ink pixels and return the largest cluster mask.

    arr: grayscale image (uint8); ink = pixel < 200

    A cell size equal to ``eps`` limits each region query to the point's
    3x3 neighboring cells. Distances and labels are computed with Torch on
    CPU tensors; CPU is deliberate because crops are small and the GPU is
    reserved for MolDet/MolParser inference.

    Returns a boolean mask (same shape as ``arr``) covering the DBSCAN
    cluster with the most ink pixels, or ``None`` when clustering is not
    applicable (Torch missing, no foreground, over the point cap, or no
    non-noise cluster formed).
    """
    torch = _get_torch()
    if torch is None:
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
    points = torch.as_tensor(coords, dtype=torch.float32, device="cpu")
    cell_coords = torch.floor(points / eps).to(dtype=torch.int64)

    # Sort cells once and retain contiguous ranges for O(1) candidate lookup.
    # Coordinates are non-negative pixel positions, so a flattened integer key
    # is sufficient and avoids a Python tuple lookup for every candidate.
    max_cell_x = int(cell_coords[:, 1].max().item())
    cell_stride = max_cell_x + 1
    cell_keys = cell_coords[:, 0] * cell_stride + cell_coords[:, 1]
    sorted_keys, order = torch.sort(cell_keys)
    unique_keys, counts = torch.unique_consecutive(sorted_keys, return_counts=True)
    starts = torch.cat(
        (
            torch.zeros(1, dtype=torch.int64),
            torch.cumsum(counts, dim=0)[:-1],
        )
    )
    cell_ranges: dict[int, tuple[int, int]] = {
        int(key): (int(start), int(start + count))
        for key, start, count in zip(
            unique_keys.tolist(), starts.tolist(), counts.tolist(), strict=True
        )
    }

    eps_squared = float(eps * eps)

    def region_query(point_index: int) -> list[int]:
        """Return all point indices within ``eps`` of one point."""
        cell_y = int(cell_coords[point_index, 0].item())
        cell_x = int(cell_coords[point_index, 1].item())
        candidate_chunks = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                neighbor_y = cell_y + dy
                neighbor_x = cell_x + dx
                if neighbor_y < 0 or neighbor_x < 0 or neighbor_x > max_cell_x:
                    continue
                cell_range = cell_ranges.get(neighbor_y * cell_stride + neighbor_x)
                if cell_range is not None:
                    start, stop = cell_range
                    candidate_chunks.append(order[start:stop])
        if not candidate_chunks:
            return []
        candidates = torch.cat(candidate_chunks)
        delta = points[candidates] - points[point_index]
        within_eps = (delta * delta).sum(dim=1) <= eps_squared
        return candidates[within_eps].tolist()

    # Standard DBSCAN expansion over the Torch-backed region queries. A Python
    # queue is intentional here: the graph traversal is irregular, while all
    # distance and neighborhood calculations remain Torch operations.
    point_count = len(coords)
    visited = [False] * point_count
    labels = [-1] * point_count
    cluster_id = 0
    with torch.inference_mode():
        for point_index in range(point_count):
            if visited[point_index]:
                continue
            visited[point_index] = True
            neighbors = region_query(point_index)
            if len(neighbors) < min_samples:
                continue

            cluster_id += 1
            labels[point_index] = cluster_id
            seeds = list(neighbors)
            queued = set(seeds)
            seed_index = 0
            while seed_index < len(seeds):
                neighbor_index = seeds[seed_index]
                seed_index += 1
                if not visited[neighbor_index]:
                    visited[neighbor_index] = True
                    neighbor_neighbors = region_query(neighbor_index)
                    if len(neighbor_neighbors) >= min_samples:
                        for candidate in neighbor_neighbors:
                            if candidate not in queued:
                                queued.add(candidate)
                                seeds.append(candidate)
                if labels[neighbor_index] == -1:
                    labels[neighbor_index] = cluster_id

    label_tensor = torch.as_tensor(labels, dtype=torch.int64, device="cpu")
    clustered = label_tensor >= 0
    if not bool(clustered.any().item()):
        return None
    cluster_ids, cluster_sizes = torch.unique(
        label_tensor[clustered], return_counts=True
    )
    largest = int(cluster_ids[cluster_sizes.argmax()].item())
    keep = (label_tensor == largest).numpy()
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
      clustering could not run (no Torch, no foreground, over the point
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

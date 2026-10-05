"""Molecule image preprocessing — applied between YOLO crop and MolParser.

Pipeline (grayscale in, grayscale out — no binarization):
1. Ink mask on the grayscale crop (pixel < 200)
2. Single-linkage clustering of the foreground ink pixels at eps=8
   (dilation by eps/2 + connected components + intersection with ink)
3. Keep the largest cluster (the molecular drawing); everything else
   (adjacent text labels, table fragments, specks) becomes ``others``

``main``/``others`` keep their original gray values: MolParser handles
antialiased strokes better than the hard 0/255 flattening we used before,
and the ink *definition* (<200) that drives the split is unchanged.

This improves MolParser accuracy on real-world patent figures where the
crop box often captures adjacent text fragments and tables. Clustering runs
on ink *pixels*, not component centroids: at 200 DPI a molecule's own atom
letters sit 20-50 px apart from each other, so centroid clustering split the
structure into fragments and discarded 70-95% of the foreground from
``main`` (measured on WO2026037254A1 crops).

The clustering step is deliberately a NumPy/SciPy morphology pipeline rather
than DBSCAN: the same mask, measured against the previous torch DBSCAN on 63
real crops from CN121270515A.pdf, has a median IoU of 1.0000 and a minimum of
0.915 (no crop below 0.9) while running 49x faster — 10.8 ms/crop against
531 ms/crop. The previous implementation pushed every seed expansion through
Python with a tensor round-trip per seed, which cost ~36% of the whole Extract
stage and got *slower* with more threads (0.49x at 4 threads).

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

# SciPy is imported lazily so a core-only install can still start the API and
# use the documented unsplit-crop fallback. The active development environment
# installs SciPy through the ``local-models`` extra.
_SCIPY_AVAILABLE: bool | None = None


def _get_ndimage() -> Any | None:
    """Return :mod:``scipy.ndimage`` when importable, caching the failure."""
    global _SCIPY_AVAILABLE
    if _SCIPY_AVAILABLE is False:
        return None
    try:
        from scipy import ndimage
    except (ImportError, OSError, RuntimeError):
        _SCIPY_AVAILABLE = False
        return None
    _SCIPY_AVAILABLE = True
    return ndimage


def _disk_structure(eps: float) -> np.ndarray:
    """Boolean disk structuring element for the clustering dilation.

    The radius is ``eps / 2``: dilating every ink pixel by half the
    neighbourhood radius makes two dilated pixels touch exactly when the two
    source pixels are at most ``eps`` apart, which reproduces DBSCAN's
    single-linkage rule without any pairwise distance computation.
    """
    radius = eps / 2.0
    span = int(np.ceil(radius))
    yy, xx = np.mgrid[-span : span + 1, -span : span + 1]
    return (yy * yy + xx * xx) <= radius * radius


#: 8-connected structure: ink is a 2D drawing, so diagonal neighbours belong to
#: the same stroke.
_CONNECTED_8 = np.ones((3, 3), dtype=bool)


def _largest_ink_cluster_mask(
    arr: np.ndarray,
    eps: float = 8.0,
    min_samples: int = 15,
) -> np.ndarray | None:
    """Cluster ink pixels and return the mask of the largest cluster.

    arr: grayscale image (uint8); ink = pixel < 200

    ``eps`` / ``min_samples`` keep the DBSCAN vocabulary the callers and tests
    already use: ``eps`` is the neighbourhood radius that decides whether two
    ink pixels belong to the same drawing, ``min_samples`` the smallest ink area
    still accepted as a drawing.

    Dilation at half the radius, one connected-component labelling, then the
    largest component intersected back with the ink mask is single-linkage
    clustering with the same ``eps`` rule. Measured against the previous torch
    DBSCAN on 63 real crops (CN121270515A.pdf): median IoU 1.0000, minimum
    0.915, no crop below 0.9, and 49x faster at 10.8 ms/crop.

    Returns a boolean mask (same shape as ``arr``) covering the cluster with the
    most ink pixels, or ``None`` when clustering is not applicable (SciPy missing,
    no foreground, or no cluster reaching ``min_samples``).
    """
    ndimage = _get_ndimage()
    if ndimage is None:
        return None

    ink = arr < 200
    if not ink.any():
        return None

    grown = ndimage.binary_dilation(ink, structure=_disk_structure(eps))
    labels, count = ndimage.label(grown, structure=_CONNECTED_8)
    if count == 0:
        return None

    # Size by ink pixels, not dilated pixels: a drawing and a nearby speck can
    # merge into one dilated component, and the larger ink area identifies the
    # drawing. Index 0 is the background label.
    ink_sizes = np.bincount(labels.ravel(), weights=ink.ravel(), minlength=count + 1)
    ink_sizes[0] = 0.0
    largest = int(np.argmax(ink_sizes))
    if ink_sizes[largest] < min_samples:
        return None

    mask = (labels == largest) & ink
    return mask if mask.any() else None


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

"""Unit tests for molecule crop preprocessing (main / others split)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

import mbforge.application.pipeline.detection.image_preprocessing as preprocess_module
from mbforge.application.pipeline.detection.image_preprocessing import (
    erase_ink_region,
    preprocess_mol_image,
    split_molecule_crop,
)


def _img(rects: list[tuple[int, int, int, int]], size: tuple[int, int] = (120, 120)):
    """White L-mode image with black half-open rects [x0, y0, x1, y1)."""
    img = Image.new("L", size, 255)
    px = img.load()
    for x0, y0, x1, y1 in rects:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = 0
    return img


def test_preprocess_separates_offcluster_label() -> None:
    """Two near strokes form the main cluster; a far label goes to others."""
    img = _img(
        [
            (10, 20, 60, 24),  # upper stroke, centroid (34.5, 21.5)
            (10, 26, 60, 30),  # lower stroke — separate component, 6px away
            (90, 90, 100, 100),  # label far away -> DBSCAN noise
        ]
    )

    main, others = preprocess_mol_image(img)

    assert others is not None
    assert int((np.asarray(main) < 200).sum()) == 50 * 4 * 2
    assert int((np.asarray(others) < 200).sum()) == 10 * 10


def test_preprocess_single_component_returns_no_others() -> None:
    """A single connected structure has nothing to separate."""
    img = _img([(10, 10, 40, 40)])

    main, others = preprocess_mol_image(img)

    assert others is None
    assert int((np.asarray(main) < 200).sum()) == 30 * 30


def test_preprocess_keeps_structure_parts_beyond_centroid_distance() -> None:
    """Atom letters far from any component centroid stay in main.

    Regression: clustering component *centroids* split the molecule when its
    parts sat more than ``eps`` from the largest component's centroid,
    discarding 70-95% of the foreground from ``main`` on real patent crops.
    Ink-pixel DBSCAN keeps every part that is within ``eps`` of structure ink.
    """
    img = _img(
        [
            (10, 20, 60, 24),  # core stroke
            (10, 26, 60, 30),  # second stroke, 2px below
            (66, 20, 76, 60),  # atom letter 6px right of the strokes
        ]
    )

    main, others = preprocess_mol_image(img)

    assert others is None
    assert int((np.asarray(main) < 200).sum()) == 50 * 4 * 2 + 10 * 40


def test_preprocess_preserves_gray_values() -> None:
    """main keeps original gray tones — no 0/255 binarization applied."""
    img = _img([(10, 10, 40, 40)])
    px = img.load()
    for x in range(10, 40):
        px[x, 12] = 150

    main, _ = preprocess_mol_image(img)

    assert int((np.asarray(main) == 150).sum()) == 30


def test_preprocess_without_torch_returns_unsplit_grayscale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Torch the grayscale image is returned unsplit."""
    monkeypatch.setattr(preprocess_module, "_TORCH_AVAILABLE", False)
    img = _img([(10, 10, 40, 40), (90, 90, 100, 100)])

    main, others = preprocess_mol_image(img)

    assert others is None
    assert int((np.asarray(main) < 200).sum()) == 30 * 30 + 10 * 10


def test_split_exposes_the_largest_cluster_mask() -> None:
    """The mask covers the drawing only, so a wider window can blank it."""
    split = split_molecule_crop(
        _img([(10, 20, 60, 24), (10, 26, 60, 30), (90, 90, 100, 100)])
    )

    assert split.main_mask is not None
    assert split.main_mask.shape == (120, 120)
    assert int(split.main_mask.sum()) == 50 * 4 * 2
    assert not split.main_mask[95, 95]  # the far label is not part of the drawing
    assert split.others is not None


def test_split_returns_no_mask_when_clustering_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Torch there is no mask, so callers must not try to erase."""
    monkeypatch.setattr(preprocess_module, "_TORCH_AVAILABLE", False)

    split = split_molecule_crop(_img([(10, 10, 40, 40)]))

    assert split.main_mask is None
    assert split.others is None


def test_erase_ink_region_blanks_the_drawing_and_keeps_everything_else() -> None:
    """Window B keeps A2 and the right/below extension; the drawing turns white."""
    a = _img([(10, 20, 60, 24), (10, 26, 60, 30), (90, 90, 100, 100)])
    split = split_molecule_crop(a)

    # B extends A to the right (x >= 120) and below (y >= 120) only, so the
    # two share the (0, 0) origin and A's mask applies to B unshifted.
    b = Image.new("L", (150, 140), 255)
    b.paste(a, (0, 0))
    band = b.load()
    for x0, y0, x1, y1 in ((124, 20, 140, 30), (20, 126, 40, 136)):
        for y in range(y0, y1):
            for x in range(x0, x1):
                band[x, y] = 0

    assert split.main_mask is not None
    erased = erase_ink_region(b, split.main_mask)

    assert erased.size == (150, 140)
    # Inside A's window only A2 (the far label) survives: 10x10 px.
    assert int((np.asarray(erased)[:120, :120] < 200).sum()) == 10 * 10
    # The extension outside A is untouched: 16x10 plus 20x10 px.
    assert int((np.asarray(erased) < 200).sum()) == 10 * 10 + 16 * 10 + 20 * 10
    # The source window is left alone — the erase is a copy.
    assert int((np.asarray(b) < 200).sum()) == 50 * 4 * 2 + 10 * 10 + 16 * 10 + 20 * 10

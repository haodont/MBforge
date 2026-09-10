"""Unit tests for molecule extraction from text and PDF images."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from mbforge.pipeline.detection.extraction import (
    MAX_SCRIBE_BATCH_SIZE,
    _clamp_scribe_batch_size,
    _nearby_page_text,
    extract_molecules_from_pdf,
    extract_molecules_from_pdf_async,
    extract_molecules_from_text,
    extract_molecules_from_text_async,
    make_candidate_id,
)


def test_nearby_page_text_keeps_local_markush_context() -> None:
    """Only text blocks near a molecule bbox are forwarded to classification."""
    blocks = [
        (0, 0, 15, 15, "Formula I, R1/R2"),
        (200, 200, 240, 220, "unrelated paragraph"),
    ]

    context = _nearby_page_text(blocks, (10, 10, 20, 20))

    assert "Formula I" in context
    assert "unrelated paragraph" not in context


def test_nearby_page_text_tolerates_missing_or_malformed_blocks() -> None:
    """Non-list block data (e.g. a failed page read) yields empty context."""
    assert _nearby_page_text(None, (0, 0, 10, 10)) == ""
    assert _nearby_page_text("not-blocks", (0, 0, 10, 10)) == ""
    assert _nearby_page_text((), (0, 0, 10, 10)) == ""


def test_clamp_scribe_batch_size_enforces_bounds() -> None:
    """Configured batch sizes are clamped into [1, MAX_SCRIBE_BATCH_SIZE]."""
    assert _clamp_scribe_batch_size(8) == 8
    assert _clamp_scribe_batch_size(1) == 1
    assert _clamp_scribe_batch_size(0) == 1
    assert _clamp_scribe_batch_size(-5) == 1
    assert _clamp_scribe_batch_size(MAX_SCRIBE_BATCH_SIZE) == MAX_SCRIBE_BATCH_SIZE
    assert _clamp_scribe_batch_size(10_000) == MAX_SCRIBE_BATCH_SIZE


@pytest.fixture(autouse=True)
def _reset_moldet_singletons():
    """Reset detector singletons so each test builds its own mock detector."""
    from mbforge.backends import moldet_v2_ft

    moldet_v2_ft._detector_singleton = None
    yield
    moldet_v2_ft._detector_singleton = None


def test_extract_molecules_from_text_finds_valid_smiles() -> None:
    """SMILES embedded in plain text are extracted and canonicalized."""
    text = "The ethanol molecule is CCO and propane is CCC"
    results = extract_molecules_from_text(text, doc_id="doc-1")

    canonicals = {r.esmiles for r in results}
    assert "CCO" in canonicals
    assert "CCC" in canonicals
    assert all(r.source == "text" for r in results)


def test_extract_molecules_from_text_ignores_invalid_tokens() -> None:
    """Random alphanumeric tokens that are not valid SMILES are skipped."""
    text = "Some abbreviations like ATP and NADPH should not parse."
    results = extract_molecules_from_text(text, doc_id="doc-1")
    assert results == []


def test_extract_molecules_from_text_deduplicates_canonical_smiles() -> None:
    """Repeated textual mentions produce one canonical candidate."""
    results = extract_molecules_from_text(
        "ethanol CCO and the same compound CCO", "doc-1"
    )
    assert len(results) == 1
    assert results[0].esmiles == "CCO"
    assert "ethanol" in results[0].context_text


def _patch_pdf_dependencies(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Set up sys.modules mocks so extract_molecules_from_pdf avoids heavy imports."""
    fake_fitz = MagicMock()
    fake_fitz.FileDataError = Exception

    fake_molparser = MagicMock()
    fake_scribe = MagicMock()
    fake_scribe.smiles = "CCO"
    fake_scribe.esmiles = "CCO"
    fake_molparser.predict_batch.return_value = [fake_scribe]

    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    fake_mol_bbox = MagicMock()
    fake_mol_bbox.category_id = 1
    fake_mol_bbox.bbox = [0.1, 0.1, 0.9, 0.9]
    fake_mol_bbox.score = 0.95

    fake_detect = MagicMock()
    fake_detect.bboxes = [fake_mol_bbox]

    return {
        "fitz": fake_fitz,
        "molparser": fake_molparser,
        "detect": fake_detect,
        "scribe": fake_scribe,
    }


def test_extract_molecules_from_pdf_mocked_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Image extraction yields ExtractionResult objects without loading models."""
    mocks = _patch_pdf_dependencies(monkeypatch)

    project_root = str(tmp_path)
    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    fake_page = MagicMock()
    fake_page.rect.width = 612.0
    fake_page.rect.height = 792.0
    fake_page.get_text.return_value = ""
    fake_page.get_images.return_value = []

    fake_pix = MagicMock()
    fake_pix.width = 2
    fake_pix.height = 2
    fake_pix.n = 3
    fake_pix.samples = bytes([255] * 12)
    fake_page.get_pixmap.return_value = fake_pix

    fake_doc = MagicMock()
    fake_doc.__len__ = MagicMock(return_value=1)
    fake_doc.load_page.return_value = fake_page
    mocks["fitz"].open.return_value = fake_doc

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules",
            return_value=mocks["detect"],
        ),
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split,
        ),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, project_root, "doc-1")

    assert len(results) == 1
    result = results[0]
    assert result.esmiles == "CCO"
    assert result.smiles == "CCO"
    assert result.source == "image"
    assert result.moldet_conf == 0.95
    assert result.page_idx == 0
    assert result.name == ""
    assert result.context_text == ""
    assert result.mol_img_path is not None
    assert result.mol_img_path.is_file()
    # Batch path: all crops for the page/doc are passed to predict_batch once.
    mocks["molparser"].predict_batch.assert_called_once()
    assert len(mocks["molparser"].predict_batch.call_args[0][0]) == 1


def test_extract_molecules_from_pdf_skips_pure_text_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pages with abundant native text and no images are skipped."""
    mocks = _patch_pdf_dependencies(monkeypatch)

    project_root = str(tmp_path)
    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    fake_page = MagicMock()
    fake_page.rect.width = 612.0
    fake_page.rect.height = 792.0
    fake_page.get_text.return_value = "A" * 1000
    fake_page.get_images.return_value = []

    fake_doc = MagicMock()
    fake_doc.__len__ = MagicMock(return_value=1)
    fake_doc.load_page.return_value = fake_page
    mocks["fitz"].open.return_value = fake_doc

    with (
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, project_root, "doc-1")

    assert results == []


def test_extract_molecules_from_pdf_returns_empty_when_detector_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If MolDetv2-FT is unavailable we bail out early with an empty list."""
    _patch_pdf_dependencies(monkeypatch)

    project_root = str(tmp_path)
    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    with (
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = False
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, project_root, "doc-1")

    assert results == []


def test_extract_molecules_from_pdf_async_offloads_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The async wrapper runs the sync extractor in asyncio.to_thread."""
    calls: list[tuple[object, ...]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return []

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    result = asyncio.run(
        extract_molecules_from_pdf_async(str(tmp_path / "x.pdf"), str(tmp_path), "doc")
    )
    assert result == []
    assert len(calls) == 1
    assert calls[0][0] is extract_molecules_from_pdf


def test_extract_molecules_from_text_async_offloads_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async wrapper runs the text extractor in asyncio.to_thread."""
    calls: list[tuple[object, ...]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return []

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    result = asyncio.run(extract_molecules_from_text_async("some text", "doc"))
    assert result == []
    assert len(calls) == 1
    assert calls[0][0] is extract_molecules_from_text


def test_make_candidate_id_deterministic_per_structure_and_position() -> None:
    """IDs are stable for identical inputs and change with any component."""
    base = make_candidate_id("doc-1", "CCO", 3, (10.0, 20.0, 30.0, 40.0))

    assert base == make_candidate_id("doc-1", "CCO", 3, (10.0, 20.0, 30.0, 40.0))
    assert base == make_candidate_id("doc-1", "CCO", 3, [10.0, 20.0, 30.0, 40.0])
    assert base != make_candidate_id("doc-2", "CCO", 3, (10.0, 20.0, 30.0, 40.0))
    assert base != make_candidate_id("doc-1", "CCOC", 3, (10.0, 20.0, 30.0, 40.0))
    assert base != make_candidate_id("doc-1", "CCO", 4, (10.0, 20.0, 30.0, 40.0))
    assert base != make_candidate_id("doc-1", "CCO", 3, None)
    assert make_candidate_id("doc-1", "CCO", None, None)


def _mol_bbox(bbox: list[float], score: float = 0.9) -> MagicMock:
    """Build a fake category-1 (molecule) detection box."""
    fake = MagicMock()
    fake.category_id = 1
    fake.bbox = bbox
    fake.score = score
    return fake


def _fake_split(image: Image.Image, **_kwargs):
    """Stand in for ``split_molecule_crop``: identity main, no offcut, no mask.

    ``main_mask=None`` is the real "clustering could not run" outcome and
    suppresses the label-image OCR entirely.
    """
    return SimpleNamespace(main=image, others=None, main_mask=None)


def _fake_split_with_empty_mask(image: Image.Image, **_kwargs):
    """Like :func:`_fake_split` but with a real (all-false) mask.

    The label image is still built — window B with nothing erased — so the
    foreground gate and the OCR plumbing are exercised.
    """
    return SimpleNamespace(
        main=image,
        others=None,
        main_mask=np.zeros((image.height, image.width), dtype=bool),
    )


def _setup_fake_page(
    mocks: dict,
    *,
    blocks: list[tuple[int, int, int, int, str]],
    dark_rect: tuple[int, int, int, int] | None = None,
) -> tuple[MagicMock, list[str]]:
    """Wire a 10x10 fake page; return the page and a log of get_text kinds."""
    get_text_kinds: list[str] = []

    def _get_text(kind: str):
        get_text_kinds.append(kind)
        if kind == "blocks":
            return blocks
        return ""

    fake_page = MagicMock()
    fake_page.rect.width = 612.0
    fake_page.rect.height = 792.0
    fake_page.get_text.side_effect = _get_text
    fake_page.get_images.return_value = []

    pixels = np.full((10, 10, 3), 255, dtype=np.uint8)
    if dark_rect is not None:
        x0, y0, x1, y1 = dark_rect
        pixels[y0:y1, x0:x1] = 0

    fake_pix = MagicMock()
    fake_pix.width = 10
    fake_pix.height = 10
    fake_pix.n = 3
    fake_pix.samples = pixels.tobytes()
    fake_page.get_pixmap.return_value = fake_pix

    fake_doc = MagicMock()
    fake_doc.__len__ = MagicMock(return_value=1)
    fake_doc.load_page.return_value = fake_page
    mocks["fitz"].open.return_value = fake_doc
    return fake_page, get_text_kinds


def test_extract_molecules_from_pdf_reads_page_blocks_once_per_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One page with several molecules calls get_text("blocks") exactly once.

    The per-molecule local-text filtering must be unchanged: each result only
    carries the block text near its own bbox.
    """
    mocks = _patch_pdf_dependencies(monkeypatch)

    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    _, get_text_kinds = _setup_fake_page(
        mocks,
        blocks=[
            (0, 0, 60, 60, "Formula I, R1"),
            (400, 500, 500, 560, "Formula II"),
            (2000, 2000, 2100, 2060, "unrelated paragraph"),
        ],
    )

    # Two molecule boxes on the same page.
    mocks["detect"].bboxes = [
        _mol_bbox([0.0, 0.0, 0.5, 0.5]),
        _mol_bbox([0.5, 0.5, 1.0, 1.0]),
    ]

    def _fake_scribe():
        scribe = MagicMock()
        scribe.smiles = "CCO"
        scribe.esmiles = "CCO"
        return scribe

    mocks["molparser"].predict_batch.side_effect = lambda images: [
        _fake_scribe() for _ in images
    ]

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules",
            return_value=mocks["detect"],
        ),
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split,
        ),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, str(tmp_path), "doc-1")

    assert len(results) == 2
    # PIPE-09: the page's blocks were read exactly once for both molecules.
    assert get_text_kinds.count("blocks") == 1
    # Local filtering unchanged: each molecule keeps only its own nearby block
    # text; the far block is excluded from both.
    assert "Formula I" in results[0].context_text
    assert "Formula II" in results[1].context_text
    for result in results:
        assert "unrelated paragraph" not in result.context_text


def test_extract_molecules_from_pdf_bounds_scribe_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crops are inferred in bounded batches and released after each batch.

    With a configured batch size of 2 and five molecules, predict_batch sees
    batch sizes [2, 2, 1], every crop image is closed after its batch, and all
    five extraction results are still produced in order.
    """
    mocks = _patch_pdf_dependencies(monkeypatch)

    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    _setup_fake_page(mocks, blocks=[(0, 0, 600, 700, "Formula I")])

    fake_config = SimpleNamespace(
        moldet=SimpleNamespace(
            detection_dpi=200.0,
            detection_batch_size=0,
            text_page_char_threshold=500,
            max_pages_per_doc=None,
            molparser_batch_size=2,
        )
    )
    monkeypatch.setattr("mbforge.utils.config.load_global_config", lambda: fake_config)

    mocks["detect"].bboxes = [
        _mol_bbox([0.0, 0.0, 0.5, 0.5]),
        _mol_bbox([0.5, 0.5, 1.0, 1.0]),
        _mol_bbox([0.0, 0.0, 1.0, 1.0]),
        _mol_bbox([0.0, 0.5, 0.5, 1.0]),
        _mol_bbox([0.5, 0.0, 1.0, 0.5]),
    ]

    batch_sizes: list[int] = []

    def _predict_batch(images: list[Image.Image]) -> list[MagicMock]:
        batch_sizes.append(len(images))
        scribe = MagicMock()
        scribe.smiles = "CCO"
        scribe.esmiles = "CCO"
        return [scribe for _ in images]

    mocks["molparser"].predict_batch.side_effect = _predict_batch

    closed_crops: list[Image.Image] = []
    original_close = Image.Image.close

    def _spy_close(self: Image.Image) -> None:
        closed_crops.append(self)
        original_close(self)

    monkeypatch.setattr(Image.Image, "close", _spy_close)

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules",
            return_value=mocks["detect"],
        ),
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split,
        ),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, str(tmp_path), "doc-1")

    assert batch_sizes == [2, 2, 1]
    assert len(results) == 5
    assert [r.page_idx for r in results] == [0, 0, 0, 0, 0]
    assert all(r.esmiles == "CCO" for r in results)
    # Every image that entered the batch lifecycle was released: per molecule
    # there are now two — the preprocessed inference crop and the enlarged
    # archive crop — so 5 molecules x 2 = 10 closes (the full page image is
    # not part of the batch lifecycle).
    assert len(closed_crops) == 10


def test_extract_molecules_from_pdf_archives_expanded_moldet_crop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Archived crop is the MolDet bbox expanded; MolParser keeps the raw crop.
    # Decoupling contract: mol_img_path must be strictly larger than the
    # detected bbox crop, while the image handed to MolParser remains the
    # original detected crop - changing one must not affect the other.
    mocks = _patch_pdf_dependencies(monkeypatch)

    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    _setup_fake_page(mocks, blocks=[])
    # Interior bbox on the 10x10 page -> pixel box (2,2,6,6), size (4,4).
    mocks["detect"].bboxes = [_mol_bbox([0.2, 0.2, 0.6, 0.6])]

    def _fake_scribe():
        scribe = MagicMock()
        scribe.smiles = "CCO"
        scribe.esmiles = "CCO"
        return scribe

    mocks["molparser"].predict_batch.side_effect = lambda images: [
        _fake_scribe() for _ in images
    ]

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules",
            return_value=mocks["detect"],
        ),
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split,
        ),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, str(tmp_path), "doc-1")

    assert len(results) == 1
    with Image.open(results[0].mol_img_path) as saved:
        # Expanded archive is strictly larger than the 4x4 detected bbox.
        assert saved.width > 4
        assert saved.height > 4
    # MolParser path unchanged: it got the untouched 4x4 detected crop,
    # not the larger archived image.
    received = mocks["molparser"].predict_batch.call_args[0][0][0]
    assert received.size == (4, 4)


def test_extract_molecules_from_pdf_collects_ocr_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Characters left in window B after the drawing is erased become ocr_labels."""
    mocks = _patch_pdf_dependencies(monkeypatch)

    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    # A 10x10 page with a 5x5 ink block. The detected box is (1,1,9,9) px and B
    # extends it to (1,1,10,10), so all the ink survives into the label image
    # and clears the 16px foreground gate.
    _setup_fake_page(mocks, blocks=[], dark_rect=(1, 1, 6, 6))

    closed: list[Image.Image] = []
    original_close = Image.Image.close

    def _spy_close(self: Image.Image) -> None:
        closed.append(self)
        original_close(self)

    monkeypatch.setattr(Image.Image, "close", _spy_close)

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules",
            return_value=mocks["detect"],
        ),
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split_with_empty_mask,
        ),
        patch(
            "mbforge.backends.ocr.crop_labels.extract_label_reads",
            return_value=[
                ("1a", 0.95, (0, 0, 10, 8), True),
                ("1", 0.95, (0, 0, 10, 9), True),
            ],
        ) as mock_ocr,
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, str(tmp_path), "doc-1")

    assert len(results) == 1
    assert results[0].name == "1"
    assert results[0].properties["ocr_labels"] == ["1", "1a"]
    assert results[0].properties["ocr_labels_primary"] == "1"
    mock_ocr.assert_called_once()
    # The label image is released after OCR rather than kept in the batch: one
    # inference crop + one archive crop + one label image.
    assert len(closed) == 3


def test_extract_molecules_from_pdf_skips_ocr_without_offcut_foreground(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A label image below the 16px foreground gate never reaches the engine."""
    mocks = _patch_pdf_dependencies(monkeypatch)

    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    # All-white page: window B carries no ink, so the label image is rejected
    # by the foreground gate before the OCR pool is ever touched.
    _setup_fake_page(mocks, blocks=[])

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules",
            return_value=mocks["detect"],
        ),
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split_with_empty_mask,
        ),
        patch(
            "mbforge.backends.ocr.crop_labels.extract_label_reads",
            return_value=["4A"],
        ) as mock_ocr,
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(pdf_path, str(tmp_path), "doc-1")

    assert len(results) == 1
    assert "ocr_labels" not in results[0].properties
    mock_ocr.assert_not_called()


def test_extract_molecules_from_pdf_batches_page_rois_into_one_gpu_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All figure ROIs of a page reach detect_molecules_batch in ONE call.

    The single-image path is never taken, and the ROI-local detection boxes
    are mapped back to page-normalized coordinates.
    """
    from mbforge.backends.moldet_v2_ft import MoleculeBbox, MoleculeResult

    mocks = _patch_pdf_dependencies(monkeypatch)

    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    _setup_fake_page(mocks, blocks=[])

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules_batch",
            return_value=[
                MoleculeResult(bboxes=[MoleculeBbox(1, (0.1, 0.2, 0.9, 0.8), 0.95)])
            ],
        ) as mock_batch,
        patch("mbforge.backends.moldet_v2_ft.detect_molecules") as mock_single,
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split,
        ),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(
            pdf_path,
            str(tmp_path),
            "doc-1",
            ocr_spans_by_page={
                0: [{"bbox": [0.0, 0.0, 306.0, 396.0], "block_type": 1}]
            },
        )

    mock_batch.assert_called_once()
    roi_images = mock_batch.call_args[0][0]
    assert len(roi_images) == 1  # the page's single figure ROI
    assert mock_batch.call_args[1]["detector"] is mock_detector
    mock_single.assert_not_called()

    assert len(results) == 1
    result = results[0]
    assert result.page_idx == 0
    assert result.moldet_conf == 0.95
    assert result.esmiles == "CCO"
    # ROI (0,5,5,10 px of the 10x10 page) + ROI-local (0.1,0.2,0.9,0.8)
    # → page px (0.5,6,4.5,9) → PDF-space bbox (lower-left origin).
    assert result.bbox_pdf == [0.0, 79.2, 244.8, 316.8]


def test_extract_molecules_from_pdf_falls_back_to_full_page_when_rois_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ROI detection that yields no molecules still runs full-page MolDet."""
    from mbforge.backends.moldet_v2_ft import MoleculeResult

    mocks = _patch_pdf_dependencies(monkeypatch)

    pdf_path = str(tmp_path / "dummy.pdf")
    Path(pdf_path).write_text("dummy")

    _setup_fake_page(mocks, blocks=[])

    with (
        patch("mbforge.backends.molparser", new=mocks["molparser"]),
        patch("mbforge.backends.moldet_v2_ft.MolDetv2Detector") as mock_detector_cls,
        patch("mbforge.infra.resource_manager.ResourceManager"),
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules_batch",
            return_value=[MoleculeResult(bboxes=[])],
        ) as mock_batch,
        patch(
            "mbforge.backends.moldet_v2_ft.detect_molecules",
            return_value=mocks["detect"],
        ) as mock_single,
        patch(
            "mbforge.pipeline.detection.image_preprocessing.split_molecule_crop",
            side_effect=_fake_split,
        ),
    ):
        mock_detector = MagicMock()
        mock_detector.is_available.return_value = True
        mock_detector_cls.return_value = mock_detector

        results = extract_molecules_from_pdf(
            pdf_path,
            str(tmp_path),
            "doc-1",
            ocr_spans_by_page={
                0: [{"bbox": [0.0, 0.0, 306.0, 396.0], "block_type": 1}]
            },
        )

    mock_batch.assert_called_once()
    mock_single.assert_called_once()
    assert len(results) == 1
    assert results[0].page_idx == 0
    assert results[0].moldet_conf == 0.95

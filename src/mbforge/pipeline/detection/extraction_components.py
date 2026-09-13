"""Components used by the PDF molecule extraction coordinator.

The public extraction entry point owns scheduling and thread lifecycle.  This
module owns the crop worker's data lifecycle: image preprocessing, optional
label OCR, bounded MolParser batches, crop archival, and result construction.
Keeping these responsibilities together makes PIL ownership explicit without
turning the extraction pipeline into a generic task framework.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ...utils.logger import get_logger
from ..cancellation import CancelCheck, TaskCancelledError
from .types import ExtractionResult

logger = get_logger("mbforge.pipeline.detection.extraction_components")

DEFAULT_SCRIBE_BATCH_SIZE = 16
MAX_SCRIBE_BATCH_SIZE = 64
_PREPROCESS_MAX_PIXELS = 1_000_000
_OCR_WINDOW_EXPAND_FRACTION = 0.15


def clamp_scribe_batch_size(configured: int) -> int:
    """Clamp a configured MolParser batch size into a safe range."""
    return max(1, min(configured, MAX_SCRIBE_BATCH_SIZE))


def ocr_label_image(image: Image.Image) -> tuple[list[str], str]:
    """Read labels from an OCR image and always release the image."""
    from ...backends.ocr.label_reader import get_label_reader
    from .recognition import select_primary_coref

    try:
        reads = get_label_reader().read(image)
        labels = [text for text, _, _, _ in reads]
        primary = select_primary_coref(
            [(text, bbox, iso) for text, _, bbox, iso in reads]
        )
        return labels, primary
    except Exception as exc:
        logger.debug("crop-label OCR failed on a label image: %s", exc)
        return [], ""
    finally:
        image.close()


def fill_ocr_slot(slot: list[Any], ocr_future: Future[Any]) -> None:
    """Store completed OCR data without blocking the MolParser worker."""
    try:
        labels, primary = ocr_future.result()
    except Exception as exc:
        logger.debug("crop-label OCR future failed: %s", exc)
        return
    if labels:
        slot.append(list(labels))
    if primary:
        slot.append(primary)


@dataclass
class PreparedCrop:
    """A crop pair and metadata waiting for one MolParser batch."""

    page_idx: int
    mol_idx: int
    bbox_pdf: list[float]
    score: float
    crop_path: Path
    nearby_text: str
    parser_image: Image.Image
    archive_image: Image.Image
    ocr_slot: list[Any]


class MolParserBatcher:
    """Own bounded MolParser batches and all images in their lifecycle."""

    def __init__(
        self,
        *,
        doc_id: str,
        write_dir: Path,
        molparser: Any,
        check: CancelCheck,
    ) -> None:
        self.doc_id = doc_id
        self.write_dir = write_dir
        self.molparser = molparser
        self.check = check
        self.pending: list[PreparedCrop] = []
        self.results: list[ExtractionResult] = []
        self.ocr_bindings: list[tuple[ExtractionResult, list[Any]]] = []

    def add(self, crop: PreparedCrop) -> None:
        self.pending.append(crop)

    def flush(self) -> None:
        """Infer, archive, and release the current batch."""
        if not self.pending:
            return

        batch = self.pending
        logger.info(
            "Flushing MolParser batch: %d crops for doc %s",
            len(batch),
            self.doc_id,
        )
        try:
            self.check()
            logger.info(
                "Calling molparser.predict_batch with %d images",
                len(batch),
            )
            try:
                scribe_results = self.molparser.predict_batch(
                    [crop.parser_image for crop in batch]
                )
            except Exception as exc:
                raise RuntimeError(
                    f"MolParser batch predict failed for doc {self.doc_id}: {exc}"
                ) from exc
            logger.info(
                "MolParser batch completed, got %d results",
                len(scribe_results),
            )
            if len(scribe_results) != len(batch):
                raise RuntimeError(
                    f"MolParser batch result count mismatch for doc {self.doc_id}: "
                    f"expected {len(batch)} crops, got {len(scribe_results)}"
                )

            for crop, scribe in zip(batch, scribe_results, strict=True):
                self.check()
                result = self._archive_and_build_result(crop, scribe)
                self.results.append(result)
                self.ocr_bindings.append((result, crop.ocr_slot))
        except TaskCancelledError:
            raise
        finally:
            self._release(batch)
            self.pending.clear()

    def discard(self) -> None:
        """Release an incomplete batch without invoking MolParser."""
        self._release(self.pending)
        self.pending.clear()

    def enrich_ocr_labels(self) -> None:
        """Apply labels that completed after a MolParser batch was flushed."""
        for result, slot in self.ocr_bindings:
            labels, primary = self._ocr_values(slot)
            if labels:
                result.name = labels[0]
                result.properties["ocr_labels"] = labels
            if primary:
                result.properties["ocr_labels_primary"] = primary

    def _archive_and_build_result(
        self,
        crop: PreparedCrop,
        scribe: Any,
    ) -> ExtractionResult:
        ocr_labels, ocr_primary = self._ocr_values(crop.ocr_slot)
        raw_smiles = getattr(scribe, "smiles", "")
        smiles = raw_smiles.strip() if isinstance(raw_smiles, str) else ""

        scribe_properties = getattr(scribe, "properties", {})
        markush = (
            isinstance(scribe_properties, dict)
            and scribe_properties.get("markush") is True
        )
        properties: dict[str, Any] = {}
        if markush:
            properties["markush"] = True
            groups = scribe_properties.get("groups")
            if isinstance(groups, str):
                properties["groups"] = groups
        if crop.nearby_text:
            properties["role_context"] = crop.nearby_text
        if ocr_labels:
            properties["ocr_labels"] = ocr_labels
        if ocr_primary:
            properties["ocr_labels_primary"] = ocr_primary

        archive_path = self.write_dir / crop.crop_path.name
        try:
            # The archive is the expanded window B. MolParser receives the
            # preprocessed main cluster A1 instead.
            crop.archive_image.save(archive_path)
            if not archive_path.is_file():
                raise OSError(f"crop archive was not created: {archive_path}")
        except Exception as exc:
            raise RuntimeError(
                f"Molecule crop archive failed for {crop.crop_path}: {exc}"
            ) from exc

        return ExtractionResult(
            esmiles=(
                scribe.esmiles.strip()
                if markush and isinstance(scribe.esmiles, str)
                else smiles
            ),
            smiles=smiles,
            name=ocr_labels[0] if ocr_labels else "",
            source="image",
            moldet_conf=crop.score,
            bbox_pdf=crop.bbox_pdf,
            page_idx=crop.page_idx,
            context_text=crop.nearby_text,
            mol_img_path=crop.crop_path,
            status="pending",
            properties=properties,
        )

    @staticmethod
    def _ocr_values(slot: list[Any]) -> tuple[list[str], str]:
        if not slot:
            return [], ""
        labels = list(slot[0]) if isinstance(slot[0], list) else []
        primary = slot[1] if len(slot) >= 2 and isinstance(slot[1], str) else ""
        if primary:
            labels = [primary, *(label for label in labels if label != primary)]
        return labels, primary

    @staticmethod
    def _release(batch: list[PreparedCrop]) -> None:
        for crop in batch:
            crop.parser_image.close()
            crop.archive_image.close()


class CropProcessor:
    """Consume detected boxes and produce extraction results in one worker."""

    def __init__(
        self,
        *,
        crop_q: Any,
        crop_dir: Path,
        write_dir: Path,
        doc_id: str,
        scribe_batch_size: int,
        check: CancelCheck,
        nearby_page_text: Callable[[object, tuple[float, float, float, float]], str],
        molparser: Any,
        ocr_reader: Callable[[Image.Image], tuple[list[str], str]],
        ocr_slot_filler: Callable[[list[Any], Future[Any]], None],
    ) -> None:
        self.crop_q = crop_q
        self.crop_dir = crop_dir
        self.doc_id = doc_id
        self.check = check
        self.nearby_page_text = nearby_page_text
        self.ocr_reader = ocr_reader
        self.ocr_slot_filler = ocr_slot_filler
        self.batcher = MolParserBatcher(
            doc_id=doc_id,
            write_dir=write_dir,
            molparser=molparser,
            check=check,
        )
        self.scribe_batch_size = scribe_batch_size
        self.error: BaseException | None = None
        self.ocr_futures: list[Future[Any]] = []

    @property
    def results(self) -> list[ExtractionResult]:
        return self.batcher.results

    def run(self) -> None:
        try:
            while True:
                payload = self.crop_q.get()
                if payload is None:
                    break
                self._process_page(*payload)
        except TaskCancelledError as exc:
            self.error = exc
        except Exception as exc:
            logger.error("Molecule preprocess worker failed: %s", exc)
            self.error = exc
        finally:
            if self.error is None:
                try:
                    if self.batcher.pending:
                        logger.info(
                            "Flushing final batch with %d remaining crops for doc %s",
                            len(self.batcher.pending),
                            self.doc_id,
                        )
                        self.batcher.flush()
                except TaskCancelledError as exc:
                    self.error = exc
                except Exception as exc:
                    logger.error("Final MolParser flush failed: %s", exc)
                    self.error = exc
            if self.error is not None:
                self.batcher.discard()

    def _process_page(
        self,
        page_idx: int,
        image: Image.Image,
        detect_result_bboxes: list[Any],
        scale_x: float,
        scale_y: float,
        page_h_pts: float,
        page_blocks: object,
    ) -> None:
        self.check()
        for mol_idx, detection in enumerate(detect_result_bboxes):
            if getattr(detection, "category_id", 1) != 1:
                continue
            self.check()
            prepared = self._prepare_crop(
                page_idx,
                mol_idx,
                image,
                detection,
                scale_x,
                scale_y,
                page_h_pts,
                page_blocks,
            )
            if prepared is None:
                continue
            self.batcher.add(prepared)
            if len(self.batcher.pending) >= self.scribe_batch_size:
                logger.info(
                    "Batch size reached (%d), flushing for doc %s",
                    self.scribe_batch_size,
                    self.doc_id,
                )
                self.batcher.flush()

    def _prepare_crop(
        self,
        page_idx: int,
        mol_idx: int,
        image: Image.Image,
        detection: Any,
        scale_x: float,
        scale_y: float,
        page_h_pts: float,
        page_blocks: object,
    ) -> PreparedCrop | None:
        px1 = int(round(detection.bbox[0] * image.width))
        py1 = int(round(detection.bbox[1] * image.height))
        px2 = int(round(detection.bbox[2] * image.width))
        py2 = int(round(detection.bbox[3] * image.height))
        if px2 <= px1 or py2 <= py1:
            return None

        box_w = px2 - px1
        box_h = py2 - py1
        pad_x = int(round(box_w * _OCR_WINDOW_EXPAND_FRACTION))
        pad_y = int(round(box_h * _OCR_WINDOW_EXPAND_FRACTION))
        wide_crop = image.crop(
            (
                px1,
                py1,
                min(image.width, px2 + pad_x),
                min(image.height, py2 + pad_y),
            )
        ).convert("L")
        raw_crop = wide_crop.crop((0, 0, box_w, box_h))

        try:
            if box_w * box_h > _PREPROCESS_MAX_PIXELS:
                crop, main_mask = raw_crop, None
            else:
                from .image_preprocessing import split_molecule_crop

                split = split_molecule_crop(raw_crop)
                crop, main_mask = split.main, split.main_mask
        except Exception as exc:
            logger.debug("split_molecule_crop failed: %s, using raw crop", exc)
            crop, main_mask = raw_crop, None

        ocr_slot = self._submit_label_ocr(wide_crop, main_mask)
        bbox_pdf = [
            round(px1 * scale_x, 2),
            round(page_h_pts - py2 * scale_y, 2),
            round(px2 * scale_x, 2),
            round(page_h_pts - py1 * scale_y, 2),
        ]
        nearby_text = self.nearby_page_text(
            page_blocks,
            (
                px1 * scale_x,
                py1 * scale_y,
                px2 * scale_x,
                py2 * scale_y,
            ),
        )
        return PreparedCrop(
            page_idx=page_idx,
            mol_idx=mol_idx,
            bbox_pdf=bbox_pdf,
            score=detection.score,
            crop_path=self.crop_dir
            / f"{self.doc_id}_page_{page_idx:04d}_mol_{mol_idx:04d}.png",
            nearby_text=nearby_text,
            parser_image=crop,
            archive_image=wide_crop,
            ocr_slot=ocr_slot,
        )

    def _submit_label_ocr(
        self,
        wide_crop: Image.Image,
        main_mask: np.ndarray | None,
    ) -> list[Any]:
        ocr_image = None
        if main_mask is not None:
            from .image_preprocessing import erase_ink_region

            ocr_image = erase_ink_region(wide_crop, main_mask)

        ocr_slot: list[Any] = []
        if ocr_image is None:
            return ocr_slot
        if int((np.asarray(ocr_image) < 200).sum()) < 16:
            ocr_image.close()
            return ocr_slot

        from ...infra.process import ocr_executor

        future = ocr_executor().submit(self.ocr_reader, ocr_image)
        future.add_done_callback(
            lambda completed, slot=ocr_slot: self.ocr_slot_filler(slot, completed)
        )
        self.ocr_futures.append(future)
        return ocr_slot

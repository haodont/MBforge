"""The crop worker: each molecule box becomes an archived crop and a recognition.

This is the last stage of the molecule pass. It owns a crop from the moment a
box is lifted off a rendered page: preprocess the drawing, hand the label
offcut to OCR, accumulate MolParser batches, archive the crop, and build the
``ExtractionResult``. Every PIL image the pass opens is released here, which is
what bounds its memory by the batch size rather than by the document.
"""

from __future__ import annotations

import queue
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from mbforge.domain.types import ExtractionResult
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.cancellation import CancelCheck, TaskCancelledError
from mbforge.service.pipeline.detection.extraction.records import DetectedPage

if TYPE_CHECKING:
    TaskHandle = Any

logger = get_logger("mbforge.service.pipeline.detection.extraction.crop_processor")

#: A drawing larger than this is passed through unsplit: clustering a crop that
#: dense costs more than the separation is worth.
_PREPROCESS_MAX_PIXELS = 1_000_000
#: How far the OCR window extends past the molecule box, as a fraction of it.
_OCR_WINDOW_EXPAND_FRACTION = 0.15


def slot_values(slot: list[Any]) -> tuple[list[str], str]:
    """Return ``(labels, primary)`` from one crop's OCR slot."""
    if not slot:
        return [], ""
    labels = list(slot[0]) if isinstance(slot[0], list) else []
    primary = slot[1] if len(slot) >= 2 and isinstance(slot[1], str) else ""
    if primary:
        labels = [primary, *(label for label in labels if label != primary)]
    return labels, primary


def slot_read_boxes(
    slot: list[Any],
    labels: list[str],
    offset: tuple[float, float],
) -> list[tuple[str, tuple[float, float, float, float], float]]:
    """Return page-frame ``(text, bbox, confidence)`` for one crop's OCR reads.

    The OCR image is the expanded window around this drawing, so a read's pixel
    position is relative to that window. ``offset`` is the window's origin on the
    page; adding it puts every print in the one frame the drawings are measured
    in. Without positions there is no geometry to assign by, and the structure is
    left unlabelled.
    """
    if len(slot) < 3 or not isinstance(slot[2], list):
        return []
    origin_x, origin_y = offset
    out: list[tuple[str, tuple[float, float, float, float], float]] = []
    for entry in slot[2]:
        if not isinstance(entry, (tuple, list)) or len(entry) < 3:
            continue
        text, confidence, box = entry[0], entry[1], entry[2]
        if not isinstance(text, str) or text not in labels:
            continue
        if not isinstance(box, (tuple, list)) or len(box) != 4:
            continue
        try:
            bbox = (
                float(box[0]) + origin_x,
                float(box[1]) + origin_y,
                float(box[2]) + origin_x,
                float(box[3]) + origin_y,
            )
            conf = float(confidence)
        except (TypeError, ValueError):
            continue
        out.append((text, bbox, conf))
    return out


def ocr_label_image(image: Image.Image) -> tuple[list[str], str, list[Any]]:
    """Read labels from an OCR image and always release the image.

    Returns ``(texts, primary, detailed)`` where ``detailed`` carries each read's
    position in the OCR image's own pixel frame. Positions are what let the page
    decide which drawing owns a number; the reader's order alone cannot.
    """
    from mbforge.service.pipeline.detection.recognition import select_primary_coref
    from mbforge.service.ports import get_runtime

    try:
        reads = get_runtime().ocr_label_reader.get_label_reader().read(image)
        labels = [text for text, _, _, _ in reads]
        primary = select_primary_coref(
            [(text, bbox, iso) for text, _, bbox, iso in reads]
        )
        detailed = [(text, confidence, bbox) for text, confidence, bbox, _ in reads]
        return labels, primary, detailed
    except Exception as exc:
        logger.debug("crop-label OCR failed on a label image: %s", exc)
        return [], "", []
    finally:
        image.close()


def fill_ocr_slot(slot: list[Any], handle: TaskHandle) -> None:
    """Store completed OCR data without blocking the MolParser worker.

    The third element carries each read's own position. Label assignment compares
    a print's position against the drawings on the page, so a label without a
    position cannot be placed — it is kept for display, never for assignment.
    """
    try:
        payload = handle.result()
    except Exception as exc:
        logger.debug("crop-label OCR future failed: %s", exc)
        return
    if not isinstance(payload, (tuple, list)) or len(payload) < 2:
        return
    if not isinstance(payload[1], str):
        # An OCR reader that reports raw ``(text, confidence, bbox, isolated)``
        # reads rather than the seam's ``(labels, primary, detailed)`` shape.
        # Keep its text so the page still gets names, but record no positions:
        # geometry cannot be reconstructed from a list that never carried them.
        reads = [entry for entry in payload if isinstance(entry, (tuple, list))]
        labels = [
            str(entry[0]) for entry in reads if entry and isinstance(entry[0], str)
        ]
        if labels:
            slot.append(labels)
        return
    labels, primary = payload[0], payload[1]
    detailed = payload[2] if len(payload) >= 3 else None
    if labels:
        slot.append(list(labels))
    if primary:
        slot.append(primary)
    if detailed:
        slot.append(list(detailed))


@dataclass
class MoleculeCrop:
    """One detected molecule, ready for a MolParser batch.

        Two images, deliberately different: ``parser_image`` is the preprocessed
        drawing (main cluster only) that the recognizer reads, while
    ``archive_image`` is the wider window kept on disk for later inspection. Both
        are owned here and closed once the batch is archived.
    """

    page_idx: int
    mol_idx: int
    bbox_pdf: tuple[float, float, float, float]
    score: float
    crop_path: Path
    nearby_text: str
    parser_image: Image.Image
    archive_image: Image.Image
    ocr_slot: list[Any]
    #: The detection box in page-IMAGE pixels, the frame crop-label OCR reports
    #: its read positions in. Label assignment needs both sides in one frame; the
    #: PDF-point bbox above cannot be compared with an OCR read's pixels.
    bbox_image: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    #: Top-left of the OCR window on the page, in page-image pixels. An OCR read
    #: is positioned relative to that window, so this converts its coordinates
    #: into the page frame the drawings are measured in.
    ocr_window_origin: tuple[float, float] = (0.0, 0.0)


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
        self.pending: list[MoleculeCrop] = []
        self.results: list[ExtractionResult] = []
        self.ocr_bindings: list[tuple[ExtractionResult, list[Any], MoleculeCrop]] = []

    def add(self, crop: MoleculeCrop) -> None:
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
                recognitions = self.molparser.predict_batch(
                    [crop.parser_image for crop in batch]
                )
            except Exception as exc:
                raise RuntimeError(
                    f"MolParser batch predict failed for doc {self.doc_id}: {exc}"
                ) from exc
            logger.info(
                "MolParser batch completed, got %d results",
                len(recognitions),
            )
            if len(recognitions) != len(batch):
                raise RuntimeError(
                    f"MolParser batch result count mismatch for doc {self.doc_id}: "
                    f"expected {len(batch)} crops, got {len(recognitions)}"
                )

            for crop, recognition in zip(batch, recognitions, strict=True):
                self.check()
                result = self._archive_and_build_result(crop, recognition)
                self.results.append(result)
                self.ocr_bindings.append((result, crop.ocr_slot, crop))
        except TaskCancelledError:
            raise
        finally:
            self._release(batch)
            self.pending.clear()

    def discard(self) -> None:
        """Release an incomplete batch without invoking MolParser."""
        self._release(self.pending)
        self.pending.clear()

    def _archive_and_build_result(
        self,
        crop: MoleculeCrop,
        recognition: Any,
    ) -> ExtractionResult:
        ocr_labels, ocr_primary = self._ocr_values(crop.ocr_slot)
        raw_smiles = getattr(recognition, "smiles", "")
        smiles = raw_smiles.strip() if isinstance(raw_smiles, str) else ""

        recognition_properties = getattr(recognition, "properties", {})
        markush = (
            isinstance(recognition_properties, dict)
            and recognition_properties.get("markush") is True
        )
        properties: dict[str, Any] = {}
        if markush:
            properties["markush"] = True
            groups = recognition_properties.get("groups")
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
            smiles=smiles,
            esmiles=(
                recognition.esmiles.strip()
                if markush and isinstance(recognition.esmiles, str)
                else smiles
            ),
            moldet_conf=crop.score,
            bbox_pdf=crop.bbox_pdf,
            page_idx=crop.page_idx,
            name=ocr_labels[0] if ocr_labels else "",
            mol_img_path=str(crop.crop_path),
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
    def _release(batch: list[MoleculeCrop]) -> None:
        for crop in batch:
            crop.parser_image.close()
            crop.archive_image.close()


class CropProcessor:
    """Consume detected boxes and produce extraction results in one worker."""

    def __init__(
        self,
        *,
        crop_q: queue.Queue[DetectedPage | None],
        crop_dir: Path,
        write_dir: Path,
        doc_id: str,
        molparser_batch_size: int,
        check: CancelCheck,
        nearby_block_text: Callable[[object, tuple[float, float, float, float]], str],
        molparser: Any,
        ocr_reader: Callable[[Image.Image], tuple[list[str], str]],
        ocr_slot_filler: Callable[[list[Any], TaskHandle], None],
    ) -> None:
        self.crop_q = crop_q
        self.crop_dir = crop_dir
        self.doc_id = doc_id
        self.check = check
        self.nearby_block_text = nearby_block_text
        self.ocr_reader = ocr_reader
        self.ocr_slot_filler = ocr_slot_filler
        self.batcher = MolParserBatcher(
            doc_id=doc_id,
            write_dir=write_dir,
            molparser=molparser,
            check=check,
        )
        self.molparser_batch_size = molparser_batch_size
        self.error: BaseException | None = None
        self.ocr_futures: list[TaskHandle] = []

    @property
    def results(self) -> list[ExtractionResult]:
        return self.batcher.results

    def run(self) -> None:
        """Consume detected pages until the sentinel, then flush the tail."""
        try:
            while True:
                page = self.crop_q.get()
                if page is None:
                    break
                self._process_page(page)
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

    def enrich_ocr_labels(self) -> None:
        """Apply the designation each structure's own printed number gives it.

        Reading a label out of one expanded box and calling it that structure's
        name is wrong on a dense page: the expansion reaches the neighbouring
        drawing's number, so a structure inherits a label it does not own.
        Measured at 300 DPI this produced 31 labels shared by two or more
        *different* structures (none of the pairs shared a molecular formula) and
        collapsed activity attribution from 58% to 0.

        So the whole page is assigned at once, by geometry: the page's settled
        cases decide its numbering convention, every print then competes for the
        drawings that convention makes plausible, and anything the geometry does
        not settle is left unlabelled rather than guessed. A structure with no
        number is recoverable; a structure with the wrong number is poison.
        """
        from mbforge.service.pipeline.detection.label_assignment import (
            LabelRead,
            StructureBox,
            assign_labels,
        )

        by_page: dict[int, list[tuple[ExtractionResult, list[Any], MoleculeCrop]]] = {}
        for result, slot, crop in self.batcher.ocr_bindings:
            by_page.setdefault(result.page_idx, []).append((result, slot, crop))

        for page_idx, bindings in by_page.items():
            structures = [
                StructureBox(
                    structure_id=f"{page_idx}:{crop.mol_idx}",
                    bbox=crop.bbox_image,
                )
                for _result, _slot, crop in bindings
            ]
            reads: list[LabelRead] = []
            for _result, slot, crop in bindings:
                labels, _primary = slot_values(slot)
                for text, box, confidence in slot_read_boxes(
                    slot, labels, crop.ocr_window_origin
                ):
                    reads.append(LabelRead(text=text, bbox=box, confidence=confidence))

            if not reads:
                # This page's reader reported no positions, so there is no
                # geometry to decide ownership with. Fall back to the crop's own
                # primary read — the previous behaviour — rather than silently
                # dropping every label on the page. A page that *does* report
                # positions is decided by geometry below.
                for result, slot, _crop in bindings:
                    labels, primary = slot_values(slot)
                    if labels:
                        result.name = primary or labels[0]
                        result.properties["ocr_labels"] = labels
                    if primary:
                        result.properties["ocr_labels_primary"] = primary
                continue

            assignment = assign_labels(structures, reads)
            # ``assignments`` maps designation -> structure id; invert it once so
            # each drawing can ask which number it owns.
            by_structure = {
                structure_id: designation
                for designation, structure_id in assignment.assignments.items()
            }

            for result, slot, crop in bindings:
                labels, primary = slot_values(slot)
                owned = by_structure.get(self._structure_key(crop))
                if owned is not None:
                    # The geometry decided which print this drawing owns.
                    result.name = owned
                    result.properties["ocr_labels"] = [owned]
                    result.properties["ocr_labels_primary"] = owned
                    continue
                if not labels:
                    continue
                # No settled owner. Keep what OCR read as unverified context only:
                # ``name`` stays empty so nothing downstream treats a proximity
                # guess as this structure's designation.
                result.properties["ocr_labels_unassigned"] = labels
                if primary:
                    result.properties["ocr_labels_unassigned_primary"] = primary

    @staticmethod
    def _structure_key(crop: MoleculeCrop) -> str:
        return f"{crop.page_idx}:{crop.mol_idx}"

    def _process_page(self, page: DetectedPage) -> None:
        """Turn every molecule box on *page* into a prepared crop."""
        self.check()
        for mol_idx, detection in enumerate(page.bboxes):
            if getattr(detection, "category_id", 1) != 1:
                continue
            self.check()
            prepared = self._prepare_crop(page, mol_idx, detection)
            if prepared is None:
                continue
            self.batcher.add(prepared)
            if len(self.batcher.pending) >= self.molparser_batch_size:
                logger.info(
                    "Batch size reached (%d), flushing for doc %s",
                    self.molparser_batch_size,
                    self.doc_id,
                )
                self.batcher.flush()

    def _prepare_crop(
        self,
        page: DetectedPage,
        mol_idx: int,
        detection: Any,
    ) -> MoleculeCrop | None:
        """Lift one detection box off *page* into an owned crop pair.

        Returns None for a degenerate box. Two crops come out of one box: the
        preprocessed drawing for the recognizer and the wider window kept as the
        archive; the caller owns both until the batch they join is released.
        """
        image = page.page.image
        page_idx = page.page.page_index
        page_h_pts = page.page.height_pt
        scale_x = page.page.scale_x
        scale_y = page.page.scale_y
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
                from mbforge.service.pipeline.detection.image_preprocessing import (
                    split_molecule_crop,
                )

                split = split_molecule_crop(raw_crop)
                crop, main_mask = split.main, split.main_mask
        except Exception as exc:
            logger.debug("split_molecule_crop failed: %s, using raw crop", exc)
            crop, main_mask = raw_crop, None

        ocr_slot = self._submit_label_ocr(wide_crop, main_mask)
        bbox_pdf = (
            round(px1 * scale_x, 2),
            round(page_h_pts - py2 * scale_y, 2),
            round(px2 * scale_x, 2),
            round(page_h_pts - py1 * scale_y, 2),
        )
        nearby_text = self.nearby_block_text(
            page.page.blocks,
            (
                px1 * scale_x,
                py1 * scale_y,
                px2 * scale_x,
                py2 * scale_y,
            ),
        )
        return MoleculeCrop(
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
            bbox_image=(float(px1), float(py1), float(px2), float(py2)),
            ocr_window_origin=(float(px1), float(py1)),
        )

    def _submit_label_ocr(
        self,
        wide_crop: Image.Image,
        main_mask: np.ndarray | None,
    ) -> list[Any]:
        ocr_image = None
        if main_mask is not None:
            from mbforge.service.pipeline.detection.image_preprocessing import (
                erase_ink_region,
            )

            ocr_image = erase_ink_region(wide_crop, main_mask)

        ocr_slot: list[Any] = []
        if ocr_image is None:
            return ocr_slot
        if int((np.asarray(ocr_image) < 200).sum()) < 16:
            ocr_image.close()
            return ocr_slot

        from mbforge.service.ports import get_runtime

        runtime = get_runtime()
        handle = runtime.process.tasks.submit(
            runtime.process.TaskPool.OCR,
            self.ocr_reader,
            ocr_image,
            on_done=lambda completed, slot=ocr_slot: self.ocr_slot_filler(
                slot, completed
            ),
        )
        self.ocr_futures.append(handle)
        return ocr_slot

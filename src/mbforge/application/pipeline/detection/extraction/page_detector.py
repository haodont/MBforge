"""MolDet page-level detection and OCR-ROI coordinate handling."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from PIL import Image

from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.detection.extraction.page_detector")


class PageDetector:
    """Run MolDet for one rendered page, optionally guided by OCR figures."""

    def __init__(
        self,
        *,
        detector: Any,
        detection_batch_size: int,
        doc_id: str,
        ocr_spans_by_page: dict[int, list[dict]] | None,
    ) -> None:
        self.detector = detector
        self.detection_batch_size = detection_batch_size
        self.doc_id = doc_id
        self.ocr_spans_by_page = ocr_spans_by_page

    def detect(
        self,
        *,
        page_idx: int,
        image: Image.Image,
        page_w_pts: float,
        page_h_pts: float,
    ) -> list[Any]:
        """Return category-1 molecule boxes in reading order."""
        from mbforge.application.ports import get_runtime

        detect_molecules = get_runtime().moldet.detect_molecules
        detect_molecules_batch = get_runtime().moldet.detect_molecules_batch

        figure_bboxes = self._figure_bboxes(page_idx)
        if not figure_bboxes:
            logger.info("Running MolDet on page %d for doc %s", page_idx, self.doc_id)
            result = detect_molecules(image, detector=self.detector)
            bboxes = result.bboxes
            logger.info(
                "MolDet found %d molecule candidates on page %d",
                len(bboxes),
                page_idx,
            )
            return self._sort(bboxes)

        roi_inputs, roi_meta = self._make_roi_inputs(
            image,
            page_w_pts,
            page_h_pts,
            figure_bboxes,
        )
        bboxes: list[Any] = []
        if roi_inputs:
            logger.info(
                "Using %d OCR figure ROIs on page %d for doc %s (batched)",
                len(roi_inputs),
                page_idx,
                self.doc_id,
            )
            roi_results = detect_molecules_batch(
                roi_inputs,
                detector=self.detector,
                max_per_call=self.detection_batch_size,
            )
            for (px1, py1, px2, py2), roi_result in zip(
                roi_meta, roi_results, strict=True
            ):
                roi_w = max(1, px2 - px1)
                roi_h = max(1, py2 - py1)
                for box in roi_result.bboxes:
                    if getattr(box, "category_id", 1) != 1:
                        continue
                    ax1 = px1 + box.bbox[0] * roi_w
                    ay1 = py1 + box.bbox[1] * roi_h
                    ax2 = px1 + box.bbox[2] * roi_w
                    ay2 = py1 + box.bbox[3] * roi_h
                    bboxes.append(
                        SimpleNamespace(
                            category_id=1,
                            bbox=[
                                ax1 / image.width,
                                ay1 / image.height,
                                ax2 / image.width,
                                ay2 / image.height,
                            ],
                            score=box.score,
                        )
                    )

        # OCR figure classification can include tables. Preserve the full-page
        # fallback so an incorrect ROI never silently drops the page.
        if not bboxes:
            logger.info(
                "No molecules inside OCR ROIs on page %d, falling back to full-page MolDet",
                page_idx,
            )
            bboxes = detect_molecules(image, detector=self.detector).bboxes
        logger.info(
            "MolDet found %d molecule candidates on page %d (ROI-guided)",
            len(bboxes),
            page_idx,
        )
        return self._sort(bboxes)

    def _figure_bboxes(
        self,
        page_idx: int,
    ) -> list[tuple[float, float, float, float]] | None:
        if self.ocr_spans_by_page is None:
            return None
        spans = self.ocr_spans_by_page.get(page_idx)
        if not spans:
            return None
        figure_bboxes = [
            tuple(span["bbox"])
            for span in spans
            if span.get("block_type") == 1 and "bbox" in span
        ]
        logger.info(
            "Page %d: OCR provided %d spans, %d are figures",
            page_idx,
            len(spans),
            len(figure_bboxes),
        )
        return figure_bboxes or None

    @staticmethod
    def _make_roi_inputs(
        image: Image.Image,
        page_w_pts: float,
        page_h_pts: float,
        figure_bboxes: list[tuple[float, float, float, float]],
    ) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]]:
        scale_x_px = image.width / page_w_pts if page_w_pts > 0 else 0
        scale_y_px = image.height / page_h_pts if page_h_pts > 0 else 0
        roi_inputs: list[Image.Image] = []
        roi_meta: list[tuple[int, int, int, int]] = []
        for x0, y0_ll, x1, y1_ll in figure_bboxes:
            px1 = int(round(x0 * scale_x_px))
            py1_top = int(round((page_h_pts - y1_ll) * scale_y_px))
            px2 = int(round(x1 * scale_x_px))
            py2_bot = int(round((page_h_pts - y0_ll) * scale_y_px))
            if px2 <= px1 or py2_bot <= py1_top:
                continue
            roi_inputs.append(image.crop((px1, py1_top, px2, py2_bot)))
            roi_meta.append((px1, py1_top, px2, py2_bot))
        return roi_inputs, roi_meta

    @staticmethod
    def _sort(bboxes: list[Any]) -> list[Any]:
        bboxes.sort(key=lambda box: (box.bbox[1], box.bbox[0]))
        return bboxes

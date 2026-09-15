"""PDF page rendering for the molecule detection pipeline."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from PIL import Image

from mbforge.pipeline.cancellation import CancelCheck, TaskCancelledError
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.detection.extraction.page_renderer")


class PageRenderer:
    """Render pages with a PyMuPDF handle owned exclusively by this thread."""

    def __init__(
        self,
        *,
        pdf_path: str,
        page_count: int,
        max_pages: int | None,
        render_dpi: float,
        text_page_char_threshold: int,
        page_q: Any,
        check: CancelCheck,
        put_bounded: Callable[[Any, object], bool],
        open_errors: tuple[type[Exception], ...],
    ) -> None:
        self.pdf_path = pdf_path
        self.page_count = page_count
        self.max_pages = max_pages
        self.render_dpi = render_dpi
        self.text_page_char_threshold = text_page_char_threshold
        self.page_q = page_q
        self.check = check
        self.put_bounded = put_bounded
        self.open_errors = open_errors
        self.error: BaseException | None = None
        self.skipped_pure_text = 0

    def run(self) -> None:
        """Render pages until exhausted, cancelled, or the consumer exits."""
        import pymupdf

        document = None
        try:
            document = pymupdf.open(self.pdf_path)
            zoom = self.render_dpi / 72.0
            matrix = pymupdf.Matrix(zoom, zoom)
            stop = min(
                self.max_pages if self.max_pages is not None else self.page_count,
                self.page_count,
            )
            for page_idx in range(stop):
                self.check()
                page = document.load_page(page_idx)

                native_text = page.get_text("text").strip()
                if (
                    len(native_text) > self.text_page_char_threshold
                    and not page.get_images()
                ):
                    self.skipped_pure_text += 1
                    continue

                try:
                    page_blocks = page.get_text("blocks")
                except Exception as exc:  # noqa: BLE001 - PDF backends vary by page type
                    logger.debug("Could not read nearby PDF text: %s", exc)
                    page_blocks = ()

                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image_array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    pixmap.n,
                )
                image = Image.fromarray(image_array)
                if not self.put_bounded(
                    self.page_q,
                    (
                        page_idx,
                        image,
                        page_blocks,
                        page.rect.width,
                        page.rect.height,
                    ),
                ):
                    return
        except TaskCancelledError as exc:
            self.error = exc
        except self.open_errors as exc:
            logger.error("Failed to open PDF %s: %s", self.pdf_path, exc)
            self.error = exc
        except Exception as exc:
            logger.error("Page rendering failed for %s: %s", self.pdf_path, exc)
            self.error = exc
        finally:
            if document is not None:
                document.close()
            self.page_q.put(None)

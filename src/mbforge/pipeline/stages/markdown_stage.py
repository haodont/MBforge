"""Stage 3: Final Markdown generation from joined source evidence.

The rough Markdown is an in-memory/staging intermediate. The durable
``document.md`` is written here after Extract and Detection have joined.
"""

import os
import tempfile
from pathlib import Path

from mbforge.core.stage import PipelineErrorCode, StageResult, register
from mbforge.pipeline.markdown.esmiles_insert import _HEADING_PATTERNS
from mbforge.pipeline.run.context import PipelineContext
from mbforge.storage.layout import LibraryLayout
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.stages.markdown")


def write_rough_markdown(
    pages: list, output_path: str, images_dir: Path | None = None
) -> None:
    """Write pages to a rough markdown with basic heading detection.

    If *images_dir* is provided and a page carries OCR-extracted image
    filenames (``page.ocr_images``), backend relative references like
    ``![](images/figure_001.jpg)`` or ``<img src="imgs/figure_001.jpg" />``
    are rewritten to absolute local paths so that the rendered Markdown can
    locate the files on disk.
    """
    lines: list[str] = []
    for _i, page in enumerate(pages):
        lines.append(f"<!-- PAGE {page.page_num} -->")
        text = page.text
        # Fix OCR-backend relative image paths when we know where images live.
        # img_name may be just a filename (e.g. "figure_001.jpg") or a
        # relative path with subdirectory (e.g. "imgs/xxx.jpg" from PaddleOCR).
        if images_dir and getattr(page, "ocr_images", None):
            for img_name in page.ocr_images:
                # If img_name contains '/', it's already a relative path like
                # "imgs/xxx.jpg". Use the basename to avoid double directory.
                safe_name = Path(img_name).name if "/" in img_name else img_name
                abs_path = (images_dir / safe_name).as_posix()
                # Markdown format: ![](imgs/filename.jpg) or ![](filename.jpg)
                md_rel_ref = f"![]({img_name})"
                text = text.replace(md_rel_ref, f"![]({abs_path})")

                # HTML format: <img src="imgs/filename.jpg" ... />
                html_rel_pattern = f'src="{img_name}"'
                text = text.replace(html_rel_pattern, f'src="{abs_path}"')

        for para in text.split("\n"):
            stripped = para.strip()
            if not stripped:
                continue
            if _HEADING_PATTERNS.match(stripped.split(".")[0].strip()):
                lines.append(f"## {stripped}")
            else:
                lines.append(stripped)
        lines.append("")
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


@register(after="join")
class MarkdownStage:
    name = "markdown"

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Build the temporary rough form and publish final Markdown.

        Reads:
            SQL-backed source evidence for ``ctx.doc_id``

        Writes:
            ctx.rough_md_path: Path
            ``storage/{doc_id}/document.md``
        """
        from mbforge.pipeline.artifacts.hydration import hydrate_context_from_artifacts

        try:
            hydrate_context_from_artifacts(ctx)
        except ValueError as exc:
            logger.error(
                "Markdown stage run without valid SQL source evidence for %s: %s",
                ctx.doc_id,
                exc,
            )
            return StageResult(
                stage="markdown",
                status="error",
                message=f"Missing valid SQL source evidence: {exc}",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )
        if ctx.extracted is None:
            return StageResult(
                stage="markdown",
                status="error",
                message="Missing extracted document",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )

        logger.info("Writing temporary rough markdown for %s", ctx.doc_id)
        _fd, _temp_str = tempfile.mkstemp(suffix=".md")
        os.close(_fd)
        ctx.rough_md_path = Path(_temp_str)
        layout = LibraryLayout(ctx.library_root)
        images_dir = layout.images_dir(ctx.doc_id)
        write_rough_markdown(
            ctx.extracted.pages, str(ctx.rough_md_path), images_dir=images_dir
        )

        from mbforge.pipeline.markdown.esmiles_insert import insert_esmiles_blocks

        document_md_path = layout.document_md(ctx.doc_id)
        insert_esmiles_blocks(
            ctx.document_evidence,
            str(document_md_path),
            candidates=ctx.candidates,
            pages=ctx.extracted.pages,
            doc_id=ctx.doc_id,
            title=ctx.doc_id,
        )
        ctx.document_md_path = document_md_path

        return StageResult(
            stage="markdown",
            status="success",
            message=f"Generated Markdown with {len(ctx.extracted.pages)} pages",
            context={
                "page_count": len(ctx.extracted.pages),
                "rough_md_path": str(ctx.rough_md_path),
                "markdown_path": str(document_md_path),
            },
        )

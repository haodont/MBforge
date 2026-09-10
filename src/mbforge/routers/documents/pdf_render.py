"""PDF rendering endpoints — page images for MoldDet.

Thin HTTP shell; rendering lives in
:mod:`mbforge.services.documents.pdf_render`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import AliasChoices, BaseModel, Field

from ...services.documents import pdf_render as pdf_render_service
from ...utils.logger import get_logger
from .._path_utils import (
    DocumentNotFoundError,
    InvalidPathError,
    resolve_client_pdf_path,
)

logger = get_logger("mbforge.pdf_render_router")

router = APIRouter()


class RenderPagesRequest(BaseModel):
    """Body for POST /render-pages."""

    pdf_path: str = ""
    page_indices: list[int] | None = None
    dpi: int = 200
    library_root: str = Field(
        default="", validation_alias=AliasChoices("library_root", "libraryRoot")
    )


@router.post("/render-pages")
async def render_pdf_pages(body: RenderPagesRequest) -> dict:
    """Render PDF pages to base64 images."""
    pdf_path = body.pdf_path

    try:
        library_root = body.library_root or None
        resolved_path = resolve_client_pdf_path(pdf_path, library_root)
    except InvalidPathError:
        raise
    except DocumentNotFoundError:
        return {"success": False, "error": f"PDF not found: {pdf_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    try:
        loop = asyncio.get_running_loop()
        pages = await loop.run_in_executor(
            None,
            pdf_render_service.render_pages_to_base64,
            str(resolved_path),
            body.page_indices,
            body.dpi,
        )
        return {"success": True, "pages": pages}
    except Exception as e:
        logger.error("PDF render failed: %s", e)
        return {"success": False, "error": str(e)}

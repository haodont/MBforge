"""PDF rendering endpoints — page images for MoldDet.

Thin HTTP shell; rendering lives in
:mod:`mbforge.service.use_cases.documents.pdf_render`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from pydantic import AliasChoices, BaseModel, Field, field_validator

from mbforge.api.http._path_utils import (
    DocumentNotFoundError,
    InvalidPathError,
    resolve_client_pdf_path,
)
from mbforge.foundation.logger import get_logger
from mbforge.service.use_cases.documents import pdf_render as pdf_render_service

logger = get_logger("mbforge.pdf_render_router")

router = APIRouter()


class RenderPagesRequest(BaseModel):
    """Body for POST /render-pages."""

    pdf_path: str = ""
    page_indices: list[int] | None = None
    dpi: int = 200
    library_root: str = Field(
        default="",
        validation_alias=AliasChoices("library_root", "libraryRoot"),
        description=(
            "Absolute library root. Omit to use the configured active library."
        ),
    )

    @field_validator("library_root")
    @classmethod
    def _library_root_must_be_absolute(cls, value: str) -> str:
        if value and not Path(value).is_absolute():
            raise ValueError(
                "library_root must be an absolute path; "
                "omit it to use the configured library"
            )
        return value


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

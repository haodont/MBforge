"""MolDetv2 main pipeline endpoints.

Rewritten 2026-07-08 to use the joint MolDetv2 detector (one model
inference) and the MolParser service for SMILES recognition. The legacy
Doc/General detector pair has been removed.

Endpoints exposed (mounted by server.py under /api/v1/moldet):
- POST /extract-pdf-page - Full PDF page pipeline: render -> detect ->
                          MolParser -> SMILES+bbox.

Removed endpoints (return 410 Gone with a migration pointer):
- /detect-page, /detect-batch, /extract-page, /coref, /coref_ft
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, Field

from mbforge.application.use_cases.molecule import detection as molecule_detection
from mbforge.foundation.errors import ValidationError
from mbforge.foundation.logger import get_logger
from mbforge.interfaces.http._path_utils import InvalidPathError, resolve_pdf_path

logger = get_logger("mbforge.interfaces.http.moldet")

router = APIRouter()


# ---------------------------------------------------------------------------
# Removed endpoints - return 410 Gone with migration pointer
# ---------------------------------------------------------------------------

_REMOVED_PATHS: dict[str, str] = {
    "/detect-page": (
        "Removed. Use POST /api/v1/moldet/extract-pdf-page "
        "(full PDF pipeline with FT detector + MolParser)."
    ),
    "/detect-batch": ("Removed. Loop /api/v1/moldet/extract-pdf-page per page."),
    "/extract-page": (
        "Removed. Use POST /api/v1/moldet/extract-pdf-page with pdf_path."
    ),
    "/coref": (
        "Removed. Coref has been removed; use POST /api/v1/moldet/extract-pdf-page "
        "for molecule detection."
    ),
    "/coref_ft": (
        "Removed. Coref has been removed; the FT detector is exposed through "
        "POST /api/v1/moldet/extract-pdf-page."
    ),
}


def _gone_response(path: str) -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content={
            "success": False,
            "error": _REMOVED_PATHS[path],
            "removed_at": "2026-07-08",
        },
    )


for _removed_path in _REMOVED_PATHS:

    @router.post(_removed_path, include_in_schema=False)
    async def _gone(request: Request, _p: str = _removed_path) -> JSONResponse:
        # include_in_schema=False keeps the 410 responses out of the OpenAPI
        # doc but the endpoint still resolves so frontends in the middle of
        # migration get a clear "this is gone" signal instead of 404.
        return _gone_response(_p)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class ExtractPageRequest(BaseModel):
    """Body for the page-extraction endpoints (legacy camelCase accepted)."""

    library_root: str = Field(
        default="", validation_alias=AliasChoices("library_root", "libraryRoot")
    )
    doc_id: str = Field(default="", validation_alias=AliasChoices("doc_id", "docId"))
    pdf_path: str = ""
    page: int = 1
    dpi: float = 300.0
    mol_conf_threshold: float = 0.3


@router.post("/extract-pdf-page")
async def extract_pdf_page(body: ExtractPageRequest) -> dict[str, Any]:
    """Full PDF page pipeline: render -> FT detect -> MolParser.

    Input fields:
        library_root + doc_id (required together, path resolved server-side)
        page (int, default 1): 1-based page number
        dpi (float, default 300): render DPI
        mol_conf_threshold (float, default 0.3): molecule confidence threshold

    Threshold note:
        The FT detector's own ``conf_threshold`` (default 0.5) gates boxes
        before the router thresholds are applied. To receive boxes in the
        0.3-0.5 range, configure the detector with a lower ``conf_threshold``;
        otherwise ``mol_conf_threshold`` values below 0.5 have no effect.

    Output:
        {
            "page_num", "width", "height", "page_w_pts", "page_h_pts", "dpi",
            "molecules": [
                {"index", "bbox": {x1, y1, x2, y2 in PDF points, lower-left origin},
                 "confidence", "smiles", "context_text"}
            ],
            "bboxes": [MoleculeBbox dicts],      # category_id = 1
            "count": N,
        }
    """
    library_root = body.library_root
    doc_id = body.doc_id
    pdf_path = body.pdf_path

    if library_root and doc_id:
        pdf_path = str(resolve_pdf_path(library_root, doc_id))
    elif pdf_path:
        # Direct absolute paths from the client are no longer trusted.
        raise InvalidPathError(
            "direct pdf_path is not allowed; provide library_root and doc_id"
        )
    else:
        raise ValidationError("library_root and doc_id are required")

    return await asyncio.to_thread(
        molecule_detection.extract_pdf_page,
        pdf_path,
        body.page,
        body.dpi,
        body.mol_conf_threshold,
    )


@router.post("/extract-pdf")
async def extract_pdf_by_doc(body: ExtractPageRequest) -> dict[str, Any]:
    """Same as /extract-pdf-page, but takes (library_root, doc_id, page)
    and resolves the absolute PDF path on the server side.

    Convenience for the frontend pdfService.ts (which works with the
    library's docId, not absolute paths).
    """
    if not body.library_root or not body.doc_id:
        raise ValidationError("library_root and doc_id are required")

    pdf_path = resolve_pdf_path(body.library_root, body.doc_id)

    body_with_path = body.model_copy(
        update={
            "pdf_path": str(pdf_path),
            "library_root": body.library_root,
            "doc_id": body.doc_id,
        }
    )
    return await extract_pdf_page(body_with_path)

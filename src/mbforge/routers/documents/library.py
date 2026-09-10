"""Library API router — unified document library.

Prefix: /api/v1/library. Thin HTTP shell: validation, streaming transport,
and async wrapping only; persistence and artifact reads live in
:mod:`mbforge.services.documents.library`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Form, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response

from ...models.library import (
    LibraryConfigureRequest,
    LibraryConfigureResponse,
    LibraryDeleteDocumentRequest,
    LibraryDocumentsResponse,
    LibraryEvidenceItem,
    LibraryImportResponse,
    LibraryListDocumentsRequest,
    LibraryMoleculeEvidenceUpdateRequest,
    LibraryMoleculeEvidenceUpdateResponse,
    LibraryStatus,
    LibrarySuccessResponse,
)
from ...services.documents import library as library_service
from ...services.documents import source_evidence
from ...utils.config import update_settings
from ...utils.errors import (
    FileAccessError,
    MBForgeError,
    ValidationError,
)
from ...utils.logger import get_logger
from .._path_utils import (
    resolve_library_root,
    resolve_library_root_candidate,
    sanitize_upload_filename,
    validate_doc_id,
)

logger = get_logger("mbforge.library_router")

router = APIRouter()


def _resolve_library_root(body: dict | None = None) -> str:
    r"""Resolve library_root from body, config, or default (~\/MBForge).

    Priority: explicit body param > stored settings.json value > ~/MBForge.
    The returned path is validated through ``resolve_library_root`` so callers
    never receive an empty or relative root.
    """
    explicit = (body or {}).get("library_root", "")
    return str(resolve_library_root(explicit or None))


class _MissingUploadError(MBForgeError):
    status_code = 400
    error_code = "missing_upload"


@router.get("/status")
async def library_status() -> LibraryStatus:
    """Get library configuration status.

    Reports `configured: true` whenever the resolved library root either was
    explicitly configured OR can be auto-created from the default (~/MBForge).
    """
    root = _resolve_library_root()

    def _status_sync() -> tuple[bool, int]:
        try:
            library_service.ensure_writable_root(root)
            store = library_service.LibraryStore.get(root)
            return True, store.doc_count()
        except (OSError, PermissionError):
            return False, 0

    configured, doc_count = await asyncio.to_thread(_status_sync)
    return LibraryStatus(configured=configured, root=root, doc_count=doc_count)


@router.post("/import")
async def library_import(
    file: UploadFile | None = None,
    title: str = Form(""),
    library_root: str | None = Form(None),
) -> LibraryImportResponse:
    """Import a PDF (or other document) into the library via multipart upload.

    The request body is consumed in 1 MiB chunks and written to a temp file
    under ``{library_root}/tmp/`` so the server never buffers the full
    payload in memory. As soon as the running byte total exceeds
    ``MAX_UPLOAD_BYTES`` the handler aborts the stream, removes the temp
    file, and raises ``UploadTooLargeError`` (HTTP 413).
    """
    if file is None:
        raise _MissingUploadError(
            "No file provided", detail="multipart file field is required"
        )
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )

    # Validate filename before reading potentially malicious payloads.
    safe_name = sanitize_upload_filename(file.filename or "")

    try:
        await asyncio.to_thread(library_service.ensure_writable_root, root)
    except OSError as e:
        raise FileAccessError("Cannot access library directory", detail=str(e)) from e

    store = library_service.LibraryStore.get(root)

    total = 0
    tmp_path: Path | None = None
    try:
        tmp_path = await asyncio.to_thread(library_service.create_upload_tmpfile, root)
        with tmp_path.open("wb") as tmp:
            while chunk := await file.read(1 << 20):  # 1 MiB
                total += len(chunk)
                if total > library_service.MAX_UPLOAD_BYTES:
                    raise library_service.UploadTooLargeError(
                        f"Upload exceeds {library_service.MAX_UPLOAD_BYTES} bytes",
                        detail=safe_name,
                    )
                await asyncio.to_thread(tmp.write, chunk)
            await asyncio.to_thread(tmp.flush)
        doc = await asyncio.to_thread(
            library_service.add_uploaded_file, store, tmp_path, safe_name, title
        )
    finally:
        if tmp_path is not None:
            await asyncio.to_thread(tmp_path.unlink, missing_ok=True)

    return LibraryImportResponse(document=doc.to_dict())


@router.post("/documents")
async def library_list_documents(
    body: LibraryListDocumentsRequest,
) -> LibraryDocumentsResponse:
    """List all documents."""
    root = _resolve_library_root(body.model_dump() if body.library_root else None)
    store = library_service.LibraryStore.get(root)
    docs = await asyncio.to_thread(store.list_documents)
    return LibraryDocumentsResponse(documents=[d.to_dict() for d in docs])


@router.post("/documents/delete")
async def library_delete_document(
    body: LibraryDeleteDocumentRequest,
) -> LibrarySuccessResponse:
    """Delete a document by doc_id."""
    root = _resolve_library_root(body.model_dump() if body.library_root else None)
    if not body.doc_id:
        raise ValidationError("doc_id is required")
    store = library_service.LibraryStore.get(root)
    await asyncio.to_thread(store.delete_document, body.doc_id)
    return LibrarySuccessResponse()


@router.post("/documents/clear")
async def library_clear_document(
    body: LibraryDeleteDocumentRequest,
) -> LibrarySuccessResponse:
    """Clear a document's pipeline outputs, restoring the pre-pipeline state."""
    root = _resolve_library_root(body.model_dump() if body.library_root else None)
    if not body.doc_id:
        raise ValidationError("doc_id is required")
    store = library_service.LibraryStore.get(root)
    await asyncio.to_thread(store.clear_pipeline_data, body.doc_id)
    return LibrarySuccessResponse()


@router.get("/documents/{doc_id}/file")
@router.head("/documents/{doc_id}/file")
async def library_get_document_file(
    doc_id: str, library_root: str | None = None
) -> FileResponse:
    """Stream the original PDF bytes for a library document."""
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    pdf_path = await asyncio.to_thread(
        library_service.resolve_document_pdf, root, doc_id
    )
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=Path(pdf_path).name,
    )


@router.get("/documents/{doc_id}/markdown")
async def library_get_markdown(
    doc_id: str, library_root: str | None = None
) -> PlainTextResponse:
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    text = await asyncio.to_thread(library_service.read_document_markdown, root, doc_id)
    return PlainTextResponse(text)


@router.get("/documents/{doc_id}/report")
async def library_get_report(doc_id: str, library_root: str | None = None) -> Response:
    """Return the pipeline report.json for a document."""
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    content = await asyncio.to_thread(
        library_service.read_document_report, root, doc_id
    )
    return Response(content=content, media_type="application/json")


@router.get("/documents/{doc_id}/patent-facts")
async def library_get_patent_facts(
    doc_id: str, library_root: str | None = None
) -> Response:
    """Return the Patent-stage facts for a document."""
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    content = await asyncio.to_thread(
        library_service.read_patent_facts, root, doc_id
    )
    return Response(content=content, media_type="application/json")


@router.get(
    "/documents/{doc_id}/evidence",
    response_model=list[LibraryEvidenceItem],
)
async def library_get_document_evidence(
    doc_id: str,
    page: int = Query(..., ge=1),
    library_root: str | None = None,
) -> list[LibraryEvidenceItem]:
    """Return the current document page's canonical SQL source evidence."""
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    validate_doc_id(doc_id)
    evidence = await asyncio.to_thread(
        source_evidence.list_evidence,
        root,
        doc_id,
        page,
    )
    return [LibraryEvidenceItem(**item.to_dict()) for item in evidence]


@router.post(
    "/documents/{doc_id}/evidence/{evidence_id}/molecule",
    response_model=LibraryMoleculeEvidenceUpdateResponse,
)
async def library_update_molecule_evidence(
    doc_id: str,
    evidence_id: str,
    body: LibraryMoleculeEvidenceUpdateRequest,
) -> LibraryMoleculeEvidenceUpdateResponse:
    """Overwrite editable molecule metadata in its canonical SQL evidence row."""
    root = _resolve_library_root(body.model_dump() if body.library_root else None)
    validate_doc_id(doc_id)
    updated_id = await asyncio.to_thread(
        source_evidence.update_molecule,
        root,
        doc_id,
        evidence_id,
        body.name,
        body.smiles,
    )
    return LibraryMoleculeEvidenceUpdateResponse(evidence_id=updated_id)


@router.get("/documents/{doc_id}/crop")
async def library_get_crop(
    doc_id: str, rel_path: str, library_root: str | None = None
) -> FileResponse:
    """Serve a single cropped molecule image.

    `rel_path` is the filename relative to `.mbforge/crops/{doc_id}/`
    (e.g. ``WO2026035726A1_20pg_page_0003_mol_0002.png``).
    """
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    target_path = await asyncio.to_thread(
        library_service.resolve_crop_path, root, doc_id, rel_path
    )
    return FileResponse(str(target_path), media_type="image/png")


@router.get("/documents/{doc_id}/images/{filename}")
async def library_get_image(
    doc_id: str, filename: str, library_root: str | None = None
) -> FileResponse:
    """Serve a figure image extracted from OCR output."""
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    target = await asyncio.to_thread(
        library_service.resolve_image_path, root, doc_id, filename
    )
    if not await asyncio.to_thread(target.is_file):
        from ...utils.errors import NotFoundError

        raise NotFoundError(f"image not found: {filename}")
    return FileResponse(
        str(target), media_type=library_service.image_media_type(filename)
    )


@router.get("/documents/{doc_id}/pages/{page}")
async def library_get_page_text(
    doc_id: str, page: int, library_root: str | None = None
) -> PlainTextResponse:
    """Return the per-page OCR text for a single page (1-based)."""
    root = _resolve_library_root(
        {"library_root": library_root} if library_root else None
    )
    text = await asyncio.to_thread(library_service.read_page_text, root, doc_id, page)
    return PlainTextResponse(text)


@router.post("/configure")
async def library_configure(body: LibraryConfigureRequest) -> LibraryConfigureResponse:
    """Configure the library root directory."""
    if not body.root:
        raise ValidationError("root is required")
    root = resolve_library_root_candidate(body.root)
    layout = library_service.LibraryLayout(root)

    def _ensure_writable() -> None:
        layout.ensure_metadata_dir()
        layout.write_test_path.write_text("ok")
        layout.write_test_path.unlink()

    try:
        await asyncio.to_thread(_ensure_writable)
    except OSError as e:
        raise FileAccessError("Directory not writable", detail=str(e)) from e
    await asyncio.to_thread(update_settings, {"library_root": str(root)})
    return LibraryConfigureResponse(root=str(root))

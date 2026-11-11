"""Read-only page and structure image capabilities exposed to agents.

Split from ``capabilities.read`` by responsibility: this module owns local
page text and rendering, molecule depiction, and MolParser recognition.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel

from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    doc_id_field,
    register,
)
from mbforge.service.use_cases.documents.library import LibraryStore


class RecognizeMoleculesInput(BaseModel):
    doc_id: str = doc_id_field()
    page: int = Field(..., ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    max_molecules: int = Field(10, ge=1, le=20)


class RecognizeMoleculesOutput(BaseModel):
    page: int
    page_width_pts: float
    page_height_pts: float
    dpi: float
    region: list[float] | None = None
    count: int
    truncated: bool
    molecules: list[dict[str, Any]]


class PageTextBlock(BaseModel):
    region_id: str
    kind: str
    type: str
    bbox_pdf: list[float]
    reading_order: int
    text: str


class OcrPageRegionInput(BaseModel):
    doc_id: str = doc_id_field()
    page: int = Field(1, ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    max_blocks: int = Field(50, ge=1, le=100)


class OcrPageRegionOutput(BaseModel):
    doc_id: str
    page: int
    page_width_pts: float
    page_height_pts: float
    dpi: float
    region: list[float] | None = None
    count: int
    truncated: bool
    text: str
    blocks: list[PageTextBlock]


class GetPageImageInput(BaseModel):
    doc_id: str = doc_id_field()
    page: int = Field(..., ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    dpi: int = Field(144, ge=72, le=200)


class GetPageImageOutput(BaseModel):
    doc_id: str
    page: int
    page_width_pts: float
    page_height_pts: float
    dpi: int
    region: list[float] | None = None
    width: int
    height: int
    image_base64: str
    mime_type: str


class RenderMoleculeImageInput(BaseModel):
    smiles: str = Field(..., min_length=1, max_length=1024)
    width: int = Field(320, ge=64, le=640)
    height: int = Field(240, ge=64, le=640)


class RenderMoleculeImageOutput(BaseModel):
    smiles: str
    width: int
    height: int
    image_base64: str
    mime_type: str = "image/png"


class PageImageAction(BaseModel):
    action: Literal["page_image"]
    doc_id: str = doc_id_field()
    page: int = Field(..., ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    dpi: int = Field(144, ge=72, le=200)


class PageMoleculesAction(BaseModel):
    action: Literal["page_molecules"]
    doc_id: str = doc_id_field()
    page: int = Field(..., ge=1)
    region: list[float] | None = Field(None, min_length=4, max_length=4)
    max_molecules: int = Field(10, ge=1, le=20)


class MoleculeImageAction(BaseModel):
    action: Literal["molecule_image"]
    smiles: str = Field(..., min_length=1, max_length=1024)
    width: int = Field(320, ge=64, le=640)
    height: int = Field(240, ge=64, le=640)


class RecognizeStructureAction(BaseModel):
    action: Literal["recognize_structure"]
    image_base64: str = Field(..., min_length=1, max_length=12_000_000)


VisualAction = Annotated[
    PageImageAction
    | PageMoleculesAction
    | MoleculeImageAction
    | RecognizeStructureAction,
    Field(discriminator="action"),
]


class VisualInput(RootModel[VisualAction]):
    """One tool, four actions, each declaring its own required parameters.

    The discriminated union resolves the branch from ``action``, so a missing
    ``doc_id``/``page`` (or a ``smiles`` sent to a page action) is a schema
    error rather than a runtime guess.

    The published schema keeps ``type: object`` at its root because agent tool
    parameters require an object root; the branch alternatives stay listed
    under ``oneOf`` with the discriminator.
    """

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: Any, handler: Any) -> Any:
        json_schema = handler(schema)
        json_schema["type"] = "object"
        return json_schema


class VisualOutput(BaseModel):
    action: Literal[
        "page_image", "page_molecules", "molecule_image", "recognize_structure"
    ]
    doc_id: str | None = None
    page: int | None = None
    page_width_pts: float | None = None
    page_height_pts: float | None = None
    dpi: int | None = None
    region: list[float] | None = None
    width: int | None = None
    height: int | None = None
    count: int | None = None
    truncated: bool | None = None
    molecules: list[dict[str, Any]] = Field(default_factory=list)
    smiles: str | None = None
    esmiles: str | None = None
    coref: list[str] = Field(default_factory=list)
    coref_primary: str | None = None
    recognized: bool | None = None
    image_base64: str | None = None
    mime_type: str | None = None


class RecognizeStructureImageInput(BaseModel):
    image_base64: str = Field(..., min_length=1, max_length=12_000_000)


class RecognizeStructureImageOutput(BaseModel):
    smiles: str
    esmiles: str
    coref: list[str] = Field(default_factory=list)
    coref_primary: str
    recognized: bool


def _decode_structure_image(payload: str) -> Any:
    """Decode one base64 image without touching the library or filesystem."""
    import base64
    import io

    from PIL import Image

    encoded = payload.strip()
    if encoded.startswith("data:"):
        _, _, encoded = encoded.partition(",")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001 - malformed client input
        raise ValidationError("image_base64 is not valid base64") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise ValidationError("image_base64 decodes to more than 8 MiB")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:  # noqa: BLE001 - malformed client input
        raise ValidationError("image_base64 is not a readable image") from exc
    if image.width > 4096 or image.height > 4096:
        raise ValidationError("image dimensions must not exceed 4096x4096")
    return image.convert("RGB")


async def recognize_molecules_capability(
    context: CapabilityContext, request: RecognizeMoleculesInput
) -> CapabilityResult:
    """Run the local MolDet + MolParser pass over one page or region."""
    from mbforge.service.use_cases.molecule.recognition import (
        recognize_page_molecules,
    )

    store = LibraryStore.get(context.library_root)
    pdf_path = await asyncio.to_thread(store.resolve_file, request.doc_id)
    if pdf_path is None:
        raise NotFoundError("document source file not found", detail=request.doc_id)
    result = await asyncio.to_thread(
        recognize_page_molecules,
        pdf_path,
        page=request.page,
        region=request.region,
        max_molecules=request.max_molecules,
    )
    return CapabilityResult(data=RecognizeMoleculesOutput(**result))


async def recognize_structure_image_capability(
    context: CapabilityContext, request: RecognizeStructureImageInput
) -> CapabilityResult:
    """Recognize one cropped structure image supplied by the caller."""
    from mbforge.service.pipeline.detection.recognition import recognize_molecule

    image = await asyncio.to_thread(_decode_structure_image, request.image_base64)
    result = await asyncio.to_thread(recognize_molecule, image)
    return CapabilityResult(
        data=RecognizeStructureImageOutput(
            smiles=result.smiles,
            esmiles=result.esmiles,
            coref=result.coref,
            coref_primary=result.coref_primary,
            recognized=bool(result.smiles or result.esmiles),
        )
    )


async def ocr_page_region_capability(
    context: CapabilityContext, request: OcrPageRegionInput
) -> CapabilityResult:
    """Read layout text from one stored page, optionally one PDF region."""
    from mbforge.service.use_cases.documents.page_text import ocr_page_region

    store = LibraryStore.get(context.library_root)
    pdf_path = await asyncio.to_thread(store.resolve_file, request.doc_id)
    if pdf_path is None:
        raise NotFoundError("document source file not found", detail=request.doc_id)
    result = await asyncio.to_thread(
        ocr_page_region,
        pdf_path,
        doc_id=request.doc_id,
        page=request.page,
        region=request.region,
        max_blocks=request.max_blocks,
    )
    return CapabilityResult(data=OcrPageRegionOutput(**result))


async def get_page_image_capability(
    context: CapabilityContext, request: GetPageImageInput
) -> CapabilityResult:
    """Render one stored page or PDF-point region for the model to inspect."""
    from mbforge.service.use_cases.documents.pdf_render import (
        render_page_image_base64,
    )

    store = LibraryStore.get(context.library_root)
    pdf_path = await asyncio.to_thread(store.resolve_file, request.doc_id)
    if pdf_path is None:
        raise NotFoundError("document source file not found", detail=request.doc_id)
    result = await asyncio.to_thread(
        render_page_image_base64,
        pdf_path,
        request.page,
        dpi=request.dpi,
        region=request.region,
    )
    return CapabilityResult(data=GetPageImageOutput(doc_id=request.doc_id, **result))


async def render_molecule_image(
    context: CapabilityContext, request: RenderMoleculeImageInput
) -> CapabilityResult:
    """Depict one SMILES (concrete or Markush) as a PNG for inline display."""
    from mbforge.service.use_cases.chem import chem as chem_service

    rendered = await asyncio.to_thread(
        chem_service.render_molecule_png_sync,
        request.smiles,
        request.width,
        request.height,
    )
    if not rendered.get("success") or not rendered.get("image_base64"):
        raise ValidationError(
            "SMILES could not be rendered",
            detail=str(rendered.get("error") or "invalid SMILES"),
        )
    return CapabilityResult(
        data=RenderMoleculeImageOutput(
            smiles=request.smiles,
            width=request.width,
            height=request.height,
            image_base64=rendered["image_base64"],
        )
    )


async def inspect_visual(
    context: CapabilityContext, request: VisualInput
) -> CapabilityResult:
    """Dispatch the image-facing actions through one model-visible tool.

    The validated branch already guarantees the parameters its action needs.
    """
    action = request.root
    if isinstance(action, PageImageAction):
        result = await get_page_image_capability(
            context,
            GetPageImageInput(
                doc_id=action.doc_id,
                page=action.page,
                region=action.region,
                dpi=action.dpi,
            ),
        )
    elif isinstance(action, PageMoleculesAction):
        result = await recognize_molecules_capability(
            context,
            RecognizeMoleculesInput(
                doc_id=action.doc_id,
                page=action.page,
                region=action.region,
                max_molecules=action.max_molecules,
            ),
        )
    elif isinstance(action, MoleculeImageAction):
        result = await render_molecule_image(
            context,
            RenderMoleculeImageInput(
                smiles=action.smiles,
                width=action.width,
                height=action.height,
            ),
        )
    else:
        result = await recognize_structure_image_capability(
            context,
            RecognizeStructureImageInput(image_base64=action.image_base64),
        )
    payload = result.data.model_dump()
    if isinstance(action, PageMoleculesAction):
        payload["doc_id"] = action.doc_id
    return CapabilityResult(
        data=VisualOutput(action=action.action, **payload),
    )


register(
    Capability(
        name="ocr_page_region",
        description="Read layout-guided local text from one page of a stored document, optionally one PDF-point region; returns text blocks and bboxes without persisting.",
        input_model=OcrPageRegionInput,
        output_model=OcrPageRegionOutput,
        mutating=False,
        handler=ocr_page_region_capability,
    )
)


register(
    Capability(
        name="inspect_visual",
        description=(
            "One visual tool whose input is a discriminated union on action: "
            "action=page_image requires doc_id+page and renders a stored page/"
            "PDF-point region as PNG; action=page_molecules requires doc_id+page "
            "and runs MolDet + MolParser on it; action=molecule_image requires "
            "smiles (concrete or Markush) and renders a PNG; "
            "action=recognize_structure requires image_base64 and runs MolParser "
            "on caller-supplied bytes. Each branch declares its own required "
            "fields, so a missing one is a schema error before any handler runs. "
            "Image actions return an attachment, page_molecules returns molecule "
            "data, and nothing is persisted. Use page_image after reading "
            "text/evidence to verify the page, page_molecules to extract "
            "structures from a stored page (no base64 needed), molecule_image to "
            "inspect a structure, and recognize_structure only for an external "
            "image."
        ),
        input_model=VisualInput,
        output_model=VisualOutput,
        mutating=False,
        handler=inspect_visual,
    )
)

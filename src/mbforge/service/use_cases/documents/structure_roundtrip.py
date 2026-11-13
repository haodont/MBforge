"""Round-trip visual verification for one recognized structure.

The visual half of "is this structure right?", complementary to the printed
mass delta in ``structure_verification``: draw the stored SMILES back with
RDKit, read that drawing with the same MolParser the pipeline used, and read
the original crop again. Two signals, both evidence for a human — never a
verdict:

- ``self_consistency``: does the drawing read back as the stored molecule? A
  divergence means the stored SMILES is visually unstable or wrong; a match
  only proves the SMILES is readable as itself.
- ``crop_consistency``: does the drawing read back as what the original crop
  reads as? This is the fidelity question — layout-invariant, because both
  sides are the recognizer's own reading rather than pixels.

Both reads share one recognizer, so a shared misreading stays consistent; the
printed-mass delta remains the independent evidence. Nothing is written and
no structure is corrected.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mbforge.foundation.errors import NotFoundError
from mbforge.foundation.logger import get_logger
from mbforge.service.use_cases.molecule.recognition import DETECT_DPI

logger = get_logger(__name__)


def _canonical(smiles: str, *, strip_stereo: bool = False) -> str:
    """Canonical SMILES, or ``""`` when the string does not parse."""
    if not smiles:
        return ""
    try:
        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return ""
        if strip_stereo:
            Chem.RemoveStereochemistry(mol)
        return Chem.MolToSmiles(mol)
    except Exception:  # noqa: BLE001 - a read surface never fails on bad input
        return ""


def _methyl_canonical(smiles: str) -> str:
    """The SMILES with every Markush dummy atom read as a methyl carbon.

    MolParser has no dummy-atom vocabulary: it reads ``*`` as a carbon. A
    Markush scaffold therefore round-trips only under this convention, so the
    comparison accepts it instead of reporting a false divergence.
    """
    if "*" not in smiles:
        return ""
    try:
        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return ""
        for atom in mol.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetAtomicNum(6)
                atom.SetIsAromatic(False)
                atom.SetNoImplicit(False)
                atom.SetNumRadicalElectrons(0)
                atom.SetNumExplicitHs(0)
        Chem.SanitizeMol(mol)
        return Chem.MolToSmiles(mol)
    except Exception:  # noqa: BLE001 - a read surface never fails on bad input
        return ""


def render_depiction(smiles: str, size: int = 512) -> Any | None:
    """Draw a SMILES as a monochrome 2D structure, or ``None`` if it cannot parse.

    Black bonds and atom labels on white, the style the document itself draws
    in, so the re-recognition sees a comparable picture.
    """
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import Draw
        from rdkit.Chem.Draw import rdMolDraw2D

        RDLogger.DisableLog("rdApp.*")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        options = rdMolDraw2D.MolDrawOptions()
        options.useBWAtomPalette = True
        options.addStereoAnnotation = True
        image = Draw.MolToImage(mol, size=(size, size), options=options)
        return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - rendering is best effort
        logger.warning("depiction render failed: %s", exc)
        return None


def _read(predict: Callable[[Any], Any], image: Any) -> str:
    """The recognizer's SMILES for one picture; ``""`` on any failure."""
    try:
        recognition = predict(image)
        return str(getattr(recognition, "smiles", "") or "").strip()
    except Exception as exc:  # noqa: BLE001 - one failed read is evidence, not an error
        logger.warning("round-trip re-recognition failed: %s", exc)
        return ""


def _compare(recovered: str, reference: str) -> str:
    """The verdict ladder between two readings of a structure.

    Either side may carry Markush dummy atoms: the recognizer keeps ``*`` on
    a patent crop but reads it as a methyl carbon on a clean depiction, so the
    two readings are also compared under the dummy-as-methyl convention, in
    both directions.
    """
    recovered_canonical = _canonical(recovered)
    if not recovered_canonical:
        return "unreadable"
    reference_canonical = _canonical(reference)
    if not reference_canonical:
        return "unreadable"
    recovered_forms = {recovered_canonical}
    reference_forms = {reference_canonical}
    for source, forms in ((recovered, recovered_forms), (reference, reference_forms)):
        methyl = _methyl_canonical(source)
        if methyl:
            forms.add(methyl)
    if recovered_forms & reference_forms:
        return "consistent"
    if _canonical(recovered, strip_stereo=True) == _canonical(
        reference, strip_stereo=True
    ):
        return "graph_consistent"
    return "divergent"


def round_trip_check(
    smiles: str,
    crop: Any | None,
    predict: Callable[[Any], Any],
) -> dict[str, Any]:
    """Render ``smiles``, re-read the drawing and the crop, compare — pure core.

    ``predict`` is the recognizer (MolParser's ``predict`` in production, a
    stub in tests); it returns an object with a ``smiles`` attribute. ``crop``
    is the original structure picture, or ``None`` when it is unavailable.
    """
    crop_smiles = _read(predict, crop) if crop is not None else ""
    crop_consistency = "no_crop" if crop is None else "unreadable"

    canonical = _canonical(smiles)
    if not canonical:
        return {
            "self_consistency": "not_renderable",
            "canonical_smiles": "",
            "recovered_smiles": "",
            "recovered_canonical": "",
            "crop_smiles": crop_smiles,
            "crop_consistency": crop_consistency,
            "depiction": None,
            "notes": ["the stored SMILES does not parse; nothing to draw"],
        }

    depiction = render_depiction(canonical)
    if depiction is None:
        return {
            "self_consistency": "not_renderable",
            "canonical_smiles": canonical,
            "recovered_smiles": "",
            "recovered_canonical": "",
            "crop_smiles": crop_smiles,
            "crop_consistency": crop_consistency,
            "depiction": None,
            "notes": ["the SMILES parses but RDKit could not draw it"],
        }

    recovered_smiles = _read(predict, depiction)
    recovered_canonical = _canonical(recovered_smiles)
    methyl_canonical = _methyl_canonical(canonical)
    verdict = _compare(recovered_smiles, canonical)
    if crop is not None:
        crop_consistency = _compare(recovered_smiles, crop_smiles)

    notes = [
        "both readings come from the same recognizer, so a shared misreading "
        "stays consistent; the printed-mass delta is the independent evidence",
    ]
    if methyl_canonical and recovered_canonical == methyl_canonical:
        notes.append(
            "the structure is a Markush scaffold; the recognizer reads dummy atoms "
            "as methyl carbons, and the drawing reads back as the same graph under "
            "that convention"
        )
    if verdict == "graph_consistent":
        notes.append(
            "the drawing reads back as the same graph but different stereo; "
            "2D depictions often lose wedge information"
        )
    if "." in canonical:
        notes.append(
            "the SMILES has several fragments (e.g. a salt); the recognizer may "
            "read back only the largest one"
        )

    return {
        "self_consistency": verdict,
        "canonical_smiles": canonical,
        "recovered_smiles": recovered_smiles,
        "recovered_canonical": recovered_canonical,
        "crop_smiles": crop_smiles,
        "crop_consistency": crop_consistency,
        "depiction": depiction,
        "notes": notes,
    }


def _crop_for_detection(pdf_path: str, page: int, bbox: Any) -> Any | None:
    """Re-render the stored page and cut the detection's box, best effort.

    ``page`` is 0-based; ``bbox`` is PDF points with a bottom-left origin, the
    convention the evidence rows use. Any failure yields ``None`` so the
    self-consistency half still runs without a picture to compare.
    """
    try:
        import numpy as np
        from PIL import Image

        from mbforge.service.use_cases.documents import pdf_render as pdf_render_service

        document = pdf_render_service.open_pdf(pdf_path)
        try:
            if page < 0 or page >= document.page_count:
                return None
            pdf_page = document.load_page(page)
            page_w = float(pdf_page.rect.width)
            page_h = float(pdf_page.rect.height)
            pix = pdf_render_service.render_page_pixmap(
                pdf_page, DETECT_DPI, alpha=False
            )
            array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            image = Image.fromarray(array)
        finally:
            document.close()

        scale_x = pix.width / page_w if page_w else 0.0
        scale_y = pix.height / page_h if page_h else 0.0
        x0, y0, x1, y1 = (float(value) for value in bbox)
        box_px = (
            x0 * scale_x,
            (page_h - y1) * scale_y,
            x1 * scale_x,
            (page_h - y0) * scale_y,
        )
        pad = 2
        left = max(0, int(box_px[0]) - pad)
        top = max(0, int(box_px[1]) - pad)
        right = min(image.width, int(box_px[2]) + pad)
        bottom = min(image.height, int(box_px[3]) + pad)
        if right <= left or bottom <= top:
            return None
        return image.crop((left, top, right, bottom)).convert("L")
    except Exception as exc:  # noqa: BLE001 - the crop is enrichment only
        logger.warning("round-trip crop failed: %s", exc)
        return None


def _image_base64(image: Any) -> str | None:
    if image is None:
        return None
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def verify_structure_roundtrip(
    library_root: str | Path,
    doc_id: str,
    evidence_id: str,
    *,
    predict: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Verify one stored structure by drawing its SMILES and reading it back.

    ``evidence_id`` selects the molecule evidence row (the id a
    ``verify_structures`` row carries). ``predict`` overrides the recognizer
    for tests; production uses the runtime MolParser singleton.
    """
    from mbforge.service.pipeline.artifacts.hydration import load_detections
    from mbforge.service.use_cases.documents.library import LibraryStore

    restored = load_detections(library_root, doc_id)
    candidates = list(restored[0]) if restored else []
    candidate = None
    detection = None
    for item in candidates:
        for det in getattr(item, "detections", None) or []:
            if str(getattr(det, "evidence_id", "")) == evidence_id:
                candidate = item
                detection = det
                break
        if candidate is not None:
            break
    if candidate is None or detection is None:
        raise NotFoundError("structure evidence not found", detail=evidence_id)

    smiles = str(
        getattr(candidate, "canonical_smiles", "")
        or getattr(candidate, "smiles", "")
        or ""
    )

    if predict is None:
        from mbforge.service.ports import get_runtime

        runtime = get_runtime()
        runtime.molparser.load()
        predict = runtime.molparser.predict

    crop = None
    pdf_path = LibraryStore.get(library_root).resolve_file(doc_id)
    page = getattr(detection, "page", None)
    bbox = getattr(detection, "bbox", None)
    if pdf_path is not None and isinstance(page, int) and bbox:
        crop = _crop_for_detection(pdf_path, page, bbox)

    result = round_trip_check(smiles, crop, predict)
    depiction = result.pop("depiction")
    return {
        "doc_id": doc_id,
        "evidence_id": evidence_id,
        "mol_id": str(getattr(candidate, "mol_id", "") or ""),
        "page": page + 1 if isinstance(page, int) else None,
        "bbox": [float(value) for value in bbox] if bbox else None,
        "smiles": str(getattr(candidate, "smiles", "") or "") or smiles,
        "image_base64": _image_base64(depiction),
        **result,
    }


__all__ = [
    "render_depiction",
    "round_trip_check",
    "verify_structure_roundtrip",
]

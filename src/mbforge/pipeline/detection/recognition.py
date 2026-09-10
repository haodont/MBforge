"""Unified molecule recognition entry — one cropped image in, four fields out.

Composes the two recognition backends over a single preprocessed crop:

1. :func:`~mbforge.pipeline.detection.image_preprocessing.preprocess_mol_image` splits
   the crop into ``main`` (the molecular drawing) and ``others`` (adjacent
   text labels / fragments).
2. ``main`` goes to MolParser (structure → Layer-1 SMILES + Layer-2 E-SMILES).
3. ``others`` goes to local RapidOCR crop-label reading (compound
   identifiers), reduced by the digit-leading/Roman-style whitelist.

Both backends degrade gracefully: an unavailable MolParser yields empty
strings; OCR problems yield an empty ``coref`` list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from ...backends import molparser
from ...backends.ocr.crop_labels import extract_label_reads
from .image_preprocessing import preprocess_mol_image

# Compound identifiers are printed bottom-right of the drawing (scheme
# numbering); labels captured from neighbouring scheme entries sit top/left
# (roi_guided_0032: '26' bottom-right beats '26-a' top-left). Position
# decides first; among reads at the same spot bare digits ('26') beat
# letter-suffixed ids ('26-a').


def select_primary_coref(
    reads: list[tuple[str, tuple[int, int, int, int], bool]],
) -> str:
    """Pick the recommended compound identifier from positioned OCR reads.

    ``reads`` are ``(text, (x0, y0, x1, y1), isolated)``; returns ``""``
    when empty. Reads that are part of a longer text line (not isolated)
    are demoted first, then the existing bottom-right rule decides, bare
    digits winning ties.
    """
    if not reads:
        return ""
    return max(
        reads,
        key=lambda r: (
            r[2],
            r[1][2] + r[1][3],
            1 if r[0].isdigit() else 0,
        ),
    )[0]


@dataclass
class RecognizedMolecule:
    """Recognition result for a single cropped molecule image.

    Attributes:
        esmiles: Layer-2 E-SMILES (``SMILES<sep>EXTENSION``), empty when the
            MolParser backend is unavailable or fails.
        smiles: Layer-1 plain SMILES (RDKit-parseable), empty under the same
            conditions.
        coref: OCR-read compound identifiers (the same values stored as
            ``properties["ocr_labels"]`` by the document pipeline).
        coref_primary: recommended single identifier (most identifier-like
            read), ``""`` when ``coref`` is empty.
    """

    esmiles: str
    smiles: str
    coref: list[str] = field(default_factory=list)
    coref_primary: str = ""


def recognize_molecule(image: Image.Image) -> RecognizedMolecule:
    """Recognize one cropped molecule image end to end.

    Serial on purpose: single-image entry, crop-label OCR costs ~0.25 s on
    CPU and the pipeline's thread orchestration only pays off for whole
    pages of many crops.
    """
    main, others = preprocess_mol_image(image)
    result = molparser.predict(main)
    reads = extract_label_reads(others) if others is not None else []
    coref = [text for text, _, _, _ in reads]
    return RecognizedMolecule(
        esmiles=result.esmiles,
        smiles=result.smiles,
        coref=coref,
        coref_primary=select_primary_coref([(t, b, iso) for t, _, b, iso in reads]),
    )

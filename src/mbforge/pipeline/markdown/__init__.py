"""Pipeline markdown stage — rough markdown assembly and E-SMILES insertion.

Detection-side modules moved to :mod:`mbforge.pipeline.detection`; the
re-exports below keep historical ``mbforge.pipeline.markdown`` imports working.
Modules may still be imported directly via their submodule paths (all existing
deep imports keep working).

Markdown-resident module map:

- ``markers`` — shared regex markers for markdown processing.
- ``esmiles_insert`` — write ``esmiles`` blocks back into the rough markdown.
"""

from __future__ import annotations

from mbforge.core.molecule import Molecule
from mbforge.core.types import DetectionSource
from mbforge.pipeline.detection.correction import correct_molecules_with_context
from mbforge.pipeline.detection.extraction import (
    candidate_id,
    extract_molecules_from_pdf,
    extract_molecules_from_text,
)
from mbforge.pipeline.detection.formula_normalization import (
    clean_markdown_file,
    normalize_patent_formulas,
)
from mbforge.pipeline.detection.image_preprocessing import preprocess_mol_image
from mbforge.pipeline.detection.label_normalization import (
    LabelKind,
    normalize_coref_label,
)
from mbforge.pipeline.detection.label_recovery import recover_labels_from_ms
from mbforge.pipeline.detection.normalization import (
    normalize_molecules,
    select_molecule_name,
)
from mbforge.pipeline.detection.structure_role import classify_structure_role

from .esmiles_insert import insert_esmiles_blocks

__all__ = [
    "DetectionSource",
    "LabelKind",
    "Molecule",
    "classify_structure_role",
    "clean_markdown_file",
    "correct_molecules_with_context",
    "extract_molecules_from_pdf",
    "extract_molecules_from_text",
    "insert_esmiles_blocks",
    "candidate_id",
    "normalize_coref_label",
    "normalize_molecules",
    "normalize_patent_formulas",
    "preprocess_mol_image",
    "recover_labels_from_ms",
    "select_molecule_name",
]

"""Pipeline markdown stage — rough markdown assembly and E-SMILES insertion.

Detection-side modules moved to :mod:`mbforge.service.pipeline.detection`; the
re-exports below keep historical ``mbforge.service.pipeline.markdown`` imports working.
Modules may still be imported directly via their submodule paths (all existing
deep imports keep working).

Markdown-resident module map:

- ``markers`` — shared regex markers for markdown processing.
- ``esmiles_insert`` — write ``esmiles`` blocks back into the rough markdown.
"""

from __future__ import annotations

from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource
from mbforge.service.pipeline.detection.correction import (
    correct_molecules_with_context,
)
from mbforge.service.pipeline.detection.extraction import (
    extract_molecules_from_pdf,
)
from mbforge.service.pipeline.detection.formula_normalization import (
    clean_markdown_file,
    normalize_patent_formulas,
)
from mbforge.service.pipeline.detection.image_preprocessing import (
    preprocess_mol_image,
)
from mbforge.service.pipeline.detection.label_normalization import (
    LabelKind,
    normalize_coref_label,
)
from mbforge.service.pipeline.detection.label_recovery import recover_labels_from_ms
from mbforge.service.pipeline.detection.normalization import (
    normalize_molecules,
    select_molecule_name,
)
from mbforge.service.pipeline.detection.structure_role import (
    classify_structure_role,
)
from mbforge.service.pipeline.markdown.esmiles_insert import insert_esmiles_blocks

__all__ = [
    "DetectionSource",
    "LabelKind",
    "Molecule",
    "classify_structure_role",
    "clean_markdown_file",
    "correct_molecules_with_context",
    "extract_molecules_from_pdf",
    "insert_esmiles_blocks",
    "normalize_coref_label",
    "normalize_molecules",
    "normalize_patent_formulas",
    "preprocess_mol_image",
    "recover_labels_from_ms",
    "select_molecule_name",
]

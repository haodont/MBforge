"""Molecule detection pipeline — image preprocessing, recognition, normalization, and roles.

Module map:

- ``image_preprocessing`` — molecule crop cleanup between YOLO crop and MolParser.
- ``extraction`` — MolDetv2 detection + MolParser recognition over rendered
  PDF pages.

- ``normalization`` — SMILES validation, canonicalization, deduplication.
- ``structure_role`` — concrete molecule vs Markush part.
- ``correction`` — context-based correction of likely misreads.
- ``label_recovery`` — MS-guided recovery of missing compound labels.
- ``label_normalization`` — deterministic coref label cleanup.
- ``formula_normalization`` — deterministic patent formula cleanup.
"""

from __future__ import annotations

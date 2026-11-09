"""Which printed designations a recognized structure candidate carries.

A structure reaches the pipeline through several label channels: the crop label
OCR read beside the drawing, a normalized coreference label, the formula header,
and ``name``. The association pass, the entry/characterization rules and the
analysis use case all have to read the same set, or one designation means two
different structures in two places.
"""

from __future__ import annotations

from typing import Any


def candidate_label_keys(candidate: Any) -> set[str]:
    """Return the ``compound`` designation keys *candidate* prints.

    Only strings the normalizer accepts as a compound designation survive; a
    printed chemistry name yields no key, so reading more channels cannot invent
    an association.
    """
    from mbforge.service.pipeline.detection.label_normalization import (
        LabelKind,
        normalize_coref_label,
    )

    properties = getattr(candidate, "properties", {})
    properties = properties if isinstance(properties, dict) else {}
    values: list[str] = []
    for key in (
        "ocr_labels_primary",
        "ocr_labels",
        "raw_coref_label",
        "normalized_label",
        "label",
        "formula_label",
    ):
        value = properties.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))

    # A designation also reaches a candidate through ``name``: when the crop's
    # label was read off the scheme rather than off a caption it is stored there
    # and nowhere else, which made the candidate invisible to every rule below.
    name = getattr(candidate, "name", "")
    if isinstance(name, str) and name.strip():
        values.append(name)

    keys: set[str] = set()
    for value in values:
        normalized = normalize_coref_label(value)
        if normalized is not None and normalized.kind is LabelKind.COMPOUND:
            keys.add(normalized.normalized)
    return keys


__all__ = ["candidate_label_keys"]

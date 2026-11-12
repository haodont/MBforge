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

    # ``labels`` holds every designation this molecule's drawings printed. A
    # drawing whose printed number never won the name (the same compound is
    # printed twice and the label stayed with neither copy) is still a drawing
    # of that compound, and reading this channel is what makes the structure
    # answer to its own designation.
    labels = getattr(candidate, "labels", None)
    if isinstance(labels, (list, tuple)):
        values.extend(item for item in labels if isinstance(item, str))

    keys: set[str] = set()
    for value in values:
        normalized = normalize_coref_label(value)
        if normalized is not None and normalized.kind is LabelKind.COMPOUND:
            keys.add(normalized.normalized)
    return keys


def candidate_designation_counts(candidate: Any) -> dict[str, int]:
    """Return how many of *candidate*'s drawings carry each designation.

    A patent prints a compound more than once, and the printings are not
    always recognized the same way. The designation the most drawings agree on
    is the compound; the others are misreadings of it, and the candidate does
    not answer to them.
    """
    from mbforge.service.pipeline.detection.label_normalization import (
        LabelKind,
        normalize_coref_label,
    )

    properties = getattr(candidate, "properties", {})
    properties = properties if isinstance(properties, dict) else {}
    claims = properties.get("detection_designations")
    if not isinstance(claims, list):
        return {}
    counts: dict[str, int] = {}
    for claim in claims:
        name = claim.get("name") if isinstance(claim, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        normalized = normalize_coref_label(name)
        if normalized is None or normalized.kind is not LabelKind.COMPOUND:
            continue
        counts[normalized.normalized] = counts.get(normalized.normalized, 0) + 1
    return counts


def candidate_owns_designation(candidate: Any, label_key: str) -> bool:
    """Return whether *candidate* answers to *label_key*.

    A candidate owns the designation its drawings agree on most: when the
    drawings of one structure carry several designations, the one the minority
    of them carry is a misreading — the drawing belongs to the compound the
    other drawings name. A candidate whose designations tie owns none of them,
    because none of them is established.
    """
    counts = candidate_designation_counts(candidate)
    if not counts:
        # No per-drawing record (a candidate from another producer): the
        # merged label set decides, as it always did.
        return label_key in candidate_label_keys(candidate)
    own = counts.get(label_key, 0)
    if own <= 0:
        return False
    return all(own > count for key, count in counts.items() if key != label_key)


__all__ = [
    "candidate_designation_counts",
    "candidate_label_keys",
    "candidate_owns_designation",
]

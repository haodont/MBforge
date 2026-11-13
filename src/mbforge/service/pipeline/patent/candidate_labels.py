"""Which printed designations a recognized structure candidate carries.

A structure reaches the pipeline through several label channels: the crop label
OCR read beside the drawing, a normalized coreference label, the formula header,
and ``name``. The association pass, the entry/characterization rules and the
analysis use case all have to read the same set, or one designation means two
different structures in two places.
"""

from __future__ import annotations

from typing import Any


def _printed_values(candidate: Any) -> list[str]:
    """Every string a candidate records a designation in."""
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
        "designation_key",
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
    return values


def candidate_printed_names(candidate: Any) -> list[str]:
    """The channel values a candidate recorded, in the order they are read."""
    return _printed_values(candidate)


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

    keys: set[str] = set()
    for value in _printed_values(candidate):
        normalized = normalize_coref_label(value)
        if normalized is not None and normalized.kind is LabelKind.COMPOUND:
            keys.add(normalized.normalized)
            keys |= _series_spelling_variants(normalized.normalized)
    return keys


def _series_spelling_variants(key: str) -> set[str]:
    """The spellings a series designation may carry for the same compound.

    The layout reads a series head ``I`` as the digit ``1`` often enough that one
    drawing is captioned ``1-256-A`` while the activity table cites ``I-256-A``.
    Both spellings name one compound in a CN series, so a key carries all of
    them; only the first character varies and only for a hyphenated series token,
    so a bare number or a chemistry name never gains a variant.
    """
    from mbforge.service.pipeline.detection.text_label_assignment import (
        _ocr_confusable_forms,
    )

    if "-" not in key or key[:1] not in ("1", "I", "i", "l"):
        return set()
    return _ocr_confusable_forms(key)


def candidate_example_keys(candidate: Any) -> set[str]:
    """Return the example designations a candidate's drawing stands for.

    A CN patent captions an example's product with the example heading itself
    (``实施例19`` under the drawn product), and the page-text naming pass stores
    the *key* it matched (``@example:19``). Those drawings answer to the example
    identity, not to a compound number, so the association needs both key spaces
    or every reading that cites ``实施例19`` stays unowned while its structure was
    recognized and drawn in the same section.
    """
    from mbforge.domain.patent import example_designation_key

    keys: set[str] = set()
    for value in _printed_values(candidate):
        key = example_designation_key(value)
        if key:
            keys.add(key)
    return keys


def candidate_designation_keys(candidate: Any) -> set[str]:
    """Return every designation key the candidate answers to, both key spaces."""
    return candidate_label_keys(candidate) | candidate_example_keys(candidate)


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
    because none of them is established. An example designation has no
    per-drawing tally (the page prints the example heading once), so the merged
    label set decides it, exactly as it does for a candidate without claims.
    """
    if label_key.startswith("@"):
        return label_key in candidate_example_keys(candidate)
    counts = candidate_designation_counts(candidate)
    if not counts:
        # No per-drawing record (a candidate from another producer): the
        # merged label set decides, as it always did.
        return label_key in candidate_label_keys(candidate)
    own = counts.get(label_key, 0)
    if own <= 0:
        # The page prints the series head as ``1`` as often as ``I``, so the tally
        # holds ``1-2`` while the activity table asks for ``I-2``. Both spellings
        # name one compound; reading the tally literally made the structure own
        # neither and left every reading that cited either unowned (found with
        # explain_reading on CN121717757A's I-2: counts {1-2: 2}, owns false).
        from mbforge.service.pipeline.detection.text_label_assignment import (
            _ocr_confusable_forms,
        )

        variants = _ocr_confusable_forms(label_key) | {label_key}
        own = max((counts.get(form, 0) for form in variants), default=0)
        if own <= 0:
            return False
        # The variant that supplied the count is this designation, not a rival.
        return all(
            own > count for key, count in counts.items() if key not in variants
        )
    return all(own > count for key, count in counts.items() if key != label_key)


__all__ = [
    "candidate_designation_keys",
    "candidate_designation_counts",
    "candidate_example_keys",
    "candidate_label_keys",
    "candidate_owns_designation",
    "candidate_printed_names",
]

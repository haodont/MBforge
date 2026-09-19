"""Hiro-Layout label vocabulary: detector label → RegionType → evidence category.

Two mapping tiers, taken from the ChemLayout source project:

    detector label (25)  →  RegionType (product vocabulary)  →  category (closed set)

The middle tier decouples the model's label table from the product vocabulary,
so swapping detectors only rewrites ``HIRO_LABEL_TO_REGION_TYPE`` while every
downstream consumer keeps reading ``RegionType`` / category.

``category`` here is **not** MBForge's evidence category module
(:mod:`mbforge.core.evidence_kind`) — this module maps to the same four closed
values (``text`` / ``table`` / ``image`` / ``molecule``) because that is the set
:func:`mbforge.core.evidence_kind.register_kind_vocab` accepts, and
:func:`kind_vocab` is what feeds an artifact's ``meta.kind_vocab``.
"""

from __future__ import annotations

#: MBForge evidence categories (the closed set in ``core.evidence_kind``).
TEXT = "text"
TABLE = "table"
IMAGE = "image"
MOLECULE = "molecule"

#: Hiro-Layout label → RegionType.
#:
#: Choices worth keeping (they are why ``chem`` is ``image`` and not something
#: new):
#:   - ``chem`` (化学式) is a structure-diagram region — the input for molecule
#:     recognition — matching how PP-DocLayoutV3 classes structures as ``image``.
#:   - ``eqn`` → ``formula`` (its own RegionType), ``rxn`` → ``reaction``.
#:   - ``noise`` keeps its own RegionType; its category is still ``image``.
HIRO_LABEL_TO_REGION_TYPE: dict[str, str] = {
    "title": "title",
    "sec": "text",
    "text": "text",
    "photo": "image",
    "seq": "table",
    "tab": "table",
    "head": "header",
    "foot": "footer",
    "draw": "image",
    "mnote": "text",
    "cap": "text",
    "struc": "image",
    "figno": "text",
    "lineno": "text",
    "colno": "text",
    "ref": "text",
    "toc": "text",
    "noise": "noise",
    "eqn": "formula",
    "chem": "image",
    "figcx": "image",
    "rxn": "reaction",
    "bib": "text",
    "srep": "text",
    "graph": "chart",
}

#: RegionType → MBForge evidence category.
REGION_TYPE_CATEGORY: dict[str, str] = {
    "text": TEXT,
    "title": TEXT,
    "formula": TEXT,
    "header": TEXT,
    "footer": TEXT,
    "page_number": TEXT,
    "table": TABLE,
    "image": IMAGE,
    "chart": IMAGE,
    "reaction": IMAGE,
    "seal": IMAGE,
    "noise": IMAGE,
    "molecule": MOLECULE,
}

#: RegionTypes that OCR should read as running text.
TEXT_REGION_TYPES: frozenset[str] = frozenset({"text", "title", "formula"})


def region_type_of(label: str) -> str:
    """RegionType of a detector label (unknown labels fall back to ``text``)."""
    return HIRO_LABEL_TO_REGION_TYPE.get(label, "text")


def category_of_region_type(region_type: str) -> str:
    """Evidence category of a RegionType (unknown types fall back to ``image``)."""
    return REGION_TYPE_CATEGORY.get(region_type, IMAGE)


def category_of_label(label: str) -> str:
    """Evidence category of a detector label."""
    return category_of_region_type(region_type_of(label))


def kind_vocab() -> dict[str, str]:
    """``{label: category}`` for an artifact's ``meta.kind_vocab``.

    Every label the detector can emit is declared here. The join stage
    registers this vocabulary, so ``category_of(kind)`` succeeds downstream —
    an undeclared label would raise ``UnknownKind`` and fail the join.
    """
    return {
        label: category_of_region_type(region_type)
        for label, region_type in HIRO_LABEL_TO_REGION_TYPE.items()
    }


__all__ = [
    "HIRO_LABEL_TO_REGION_TYPE",
    "IMAGE",
    "MOLECULE",
    "REGION_TYPE_CATEGORY",
    "TABLE",
    "TEXT",
    "TEXT_REGION_TYPES",
    "category_of_label",
    "category_of_region_type",
    "kind_vocab",
    "region_type_of",
]

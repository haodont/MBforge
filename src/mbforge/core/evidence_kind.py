"""Evidence ``kind`` is a free-form producer label; stages only compare categories.

``SourceEvidence.kind`` accepts any non-empty string.  A producer names its own
regions — a layout model's class (``chem`` / ``figcx`` / ``mnote`` …), a molecule
detector's ``molecule``.  Nothing is rejected and no detection detail is lost.

Every label carries a **category**.  Categories are a small closed set
(:data:`CATEGORIES`); labels are open.  A label is registered where it is produced:
an external producer declares its vocabulary in the artifact it writes under
``meta.kind_vocab``; code inside MBForge that mints labels registers them in the
module that mints them.

Lookups are exact.  ``category_of`` raises :class:`UnknownKind` for a label nobody
registered — a region whose meaning was never declared is a defect to fix, not
something to silently classify as a figure.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

TEXT = "text"
TABLE = "table"
IMAGE = "image"
MOLECULE = "molecule"

#: The closed category set.  Every registered label maps to one of these.
CATEGORIES = frozenset({TEXT, TABLE, IMAGE, MOLECULE})

#: Categories whose evidence renders as page text.
TEXT_CATEGORIES = frozenset({TEXT, TABLE})

#: Reading order: text, then tables, then figures, then molecules.
_CATEGORY_ORDER = {TEXT: 0, TABLE: 1, IMAGE: 2, MOLECULE: 3}

_KIND_CATEGORY: dict[str, str] = {}


class UnknownCategory(ValueError):
    """A registration named a category outside :data:`CATEGORIES`."""


class UnknownKind(KeyError):
    """A label was queried before anyone registered it."""


def register_kind(kind: str, category: str) -> None:
    """Give a producer label its category."""
    if not kind:
        raise ValueError("kind must not be empty")
    if category not in CATEGORIES:
        raise UnknownCategory(
            f"unknown category {category!r}; expected one of {sorted(CATEGORIES)}"
        )
    _KIND_CATEGORY[kind] = category


def register_kinds(mapping: Mapping[str, str]) -> None:
    """Bulk form of :func:`register_kind`."""
    for kind, category in mapping.items():
        register_kind(kind, category)


def register_kind_vocab(meta: Mapping[str, object]) -> None:
    """Register the ``kind_vocab`` a producer declared in its artifact ``meta``.

    A producer that declares no vocabulary registers nothing here.
    """
    vocab = meta.get("kind_vocab")
    if vocab is None:
        return
    register_kinds(vocab)  # type: ignore[arg-type]


def category_of(kind: str) -> str:
    """Category of a producer label."""
    try:
        return _KIND_CATEGORY[kind]
    except KeyError:
        raise UnknownKind(
            f"kind {kind!r} is not registered — declare it in the producing "
            f"artifact's meta.kind_vocab, or where the label is minted"
        ) from None


def is_text(kind: str) -> bool:
    """True when this evidence belongs in the page's text stream."""
    return category_of(kind) in TEXT_CATEGORIES


def kind_rank(kind: str) -> int:
    """Sort rank for reading order."""
    return _CATEGORY_ORDER[category_of(kind)]


def kind_categories() -> Mapping[str, str]:
    """Read-only view of the registry."""
    return MappingProxyType(_KIND_CATEGORY)

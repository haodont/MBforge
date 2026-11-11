"""Resolve a human document reference to the canonical ``doc_id``.

``doc_id`` is the SHA-256 of the stored bytes, so it is a 64-character hex
string that nobody holds in their head. The reference a person actually has is
the document title, the file name, or the beginning of the hash — sometimes
printed in a paper or a chat message. This module turns any of those into the
one canonical id, and refuses to guess when a reference is ambiguous.

Matching is exact by design. Substring or fuzzy matching could silently point
a capability at the wrong patent, so anything that is not an exact id, prefix,
file name, or title stays unresolved.
"""

from __future__ import annotations

import re
from typing import Any

from mbforge.foundation.errors import ValidationError

#: Length of a full ``doc_id`` (SHA-256 hex).
DOC_ID_LENGTH = 64

#: Shortest accepted hash prefix. Below this, collisions get likely.
MIN_PREFIX_LENGTH = 8

#: Prefix length shown to people. 48 bits: at 10k documents the chance of any
#: two ids sharing this prefix is about 1.8e-7, while 32 bits already reaches
#: ~1.2%. The full id is still the only stored key.
DISPLAY_PREFIX_LENGTH = 12

_HEX = re.compile(r"\A[0-9a-f]+\Z")


def short_doc_id(doc_id: str) -> str:
    """Return the quotable short form of *doc_id* (its first 12 hex chars)."""
    return doc_id[:DISPLAY_PREFIX_LENGTH]


def is_full_doc_id(reference: str) -> bool:
    """Return whether *reference* is a complete SHA-256 doc id."""
    return len(reference) == DOC_ID_LENGTH and bool(_HEX.match(reference))


def _candidates(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "short_id": short_doc_id(str(row["doc_id"])),
            "title": str(row.get("title") or ""),
            "file_name": str(row.get("file_name") or ""),
        }
        for row in rows
    ]


def _ambiguous(reference: str, rows: list[dict[str, Any]]) -> ValidationError:
    return ValidationError(
        "ambiguous document reference",
        detail=reference,
        context={"candidates": _candidates(rows)},
    )


def resolve_reference(rows: list[dict[str, Any]], reference: str) -> str | None:
    """Return the canonical ``doc_id`` for *reference*, or ``None``.

    *rows* are the registered document rows. The lookup order is:

    1. an exact ``doc_id``;
    2. a unique hex prefix of at least :data:`MIN_PREFIX_LENGTH` characters;
    3. an exact file name;
    4. an exact title.

    A reference that matches several documents raises :class:`ValidationError`
    instead of picking one: the caller must disambiguate.
    """
    ref = reference.strip()
    if not ref:
        return None

    if is_full_doc_id(ref):
        for row in rows:
            if row["doc_id"] == ref:
                return ref
        return None

    if len(ref) >= MIN_PREFIX_LENGTH and _HEX.match(ref):
        prefix_matches = [row for row in rows if str(row["doc_id"]).startswith(ref)]
        if len(prefix_matches) == 1:
            return str(prefix_matches[0]["doc_id"])
        if len(prefix_matches) > 1:
            raise _ambiguous(ref, prefix_matches)

    folded = ref.casefold()
    file_matches = [
        row for row in rows if str(row.get("file_name") or "").casefold() == folded
    ]
    if len(file_matches) == 1:
        return str(file_matches[0]["doc_id"])
    if len(file_matches) > 1:
        raise _ambiguous(ref, file_matches)

    title_matches = [
        row for row in rows if str(row.get("title") or "").casefold() == folded
    ]
    if len(title_matches) == 1:
        return str(title_matches[0]["doc_id"])
    if len(title_matches) > 1:
        raise _ambiguous(ref, title_matches)

    return None


__all__ = [
    "DISPLAY_PREFIX_LENGTH",
    "DOC_ID_LENGTH",
    "MIN_PREFIX_LENGTH",
    "is_full_doc_id",
    "resolve_reference",
    "short_doc_id",
]

"""Identity derivation for Markush review candidates.

Owns the ``source_key`` / ``content_hash`` derivation used to identify a
candidate across re-imports. Pure functions: no DB I/O.

The re-import protection rule lives with the persistence path in
:mod:`mbforge.adapters.persistence.markush_candidates`:

- same ``source_key`` + same ``content_hash`` is a no-op (preserving
  human state);
- same ``source_key`` + different ``content_hash`` supersedes the prior
  row and inserts a new ``pending`` row;
- new ``source_key`` inserts a new ``pending`` row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mbforge.foundation.ids import stable_id

if TYPE_CHECKING:
    from mbforge.domain.molecule import Molecule

# Bounding boxes are quantized to 0.1 pt before joining into source_key
# so sub-pixel OCR jitter does not produce a different identity.
_BBOX_QUANTUM = 0.1
_RECOGNITION_VERSION = 1


def _quantize_coord(coord: float) -> float:
    """Round to the bbox quantum using round-half-up semantics.

    Python's built-in ``round`` uses banker's rounding (round-half-to-even),
    which gives different results for ``10.05`` and ``10.10`` even though
    both should map to the same 0.1-pt bucket. We quantize explicitly
    here so the resulting string is stable regardless of float noise.
    """
    scaled = coord / _BBOX_QUANTUM
    if scaled >= 0:
        return int(scaled + 0.5) * _BBOX_QUANTUM
    # Negative coordinates: floor towards zero so ``-10.05`` rounds to
    # ``-10.0`` rather than ``-10.1`` (the symmetric choice would be
    # round-half-away-from-zero, but rounding to the nearer quantum is
    # what users expect for bbox coordinates).
    return -int(-scaled + 0.5) * _BBOX_QUANTUM


def _quantize_bbox(
    bbox: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    """Round bbox coordinates to the nearest quantum for stable hashing."""
    if bbox is None:
        return None
    return tuple(_quantize_coord(coord) for coord in bbox)  # type: ignore[return-value]


def compute_source_key(
    doc_id: str,
    page: int | None,
    bbox: tuple[float, float, float, float] | None,
    normalized_label: str,
) -> str:
    """Return the stable identity for a review candidate.

    The key is the join of ``doc_id + page + quantized_bbox +
    normalized_label``; every component is normalized to ASCII so the
    result can be indexed in SQLite without collator gymnastics.
    """
    quantized = _quantize_bbox(bbox)
    return "|".join(
        [
            str(doc_id),
            "" if page is None else str(page),
            "" if quantized is None else ",".join(f"{c:.1f}" for c in quantized),
            normalized_label or "",
        ]
    )


def compute_content_hash(
    canonical_smiles: str,
    esmiles: str,
    context: str,
    recognition_version: int = _RECOGNITION_VERSION,
) -> str:
    """Hash the structural identity of a candidate.

    The hash folds canonical SMILES, raw e-SMILES, the captured context
    text, and the recognition version. A change in any of these forces a
    ``superseded`` + new ``pending`` pair on re-import.
    """
    return stable_id(
        "content",
        canonical_smiles or "",
        esmiles or "",
        context or "",
        str(recognition_version),
    )


def _join_context_text(molecule: Molecule) -> str:
    """Concatenate the role contexts into a single stable string for hashing."""
    contexts = molecule.properties.get("role_contexts") or []
    if isinstance(contexts, list):
        return "\n".join(str(item) for item in contexts)
    return str(contexts)


def _candidate_properties(molecule: Molecule) -> dict[str, Any]:
    """Return a JSON-safe subset of the molecule's properties for storage."""
    properties = dict(molecule.properties)
    # The properties blob in the DB carries the full classifier output
    # plus the canonical label triple. We do not sanitise the keys —
    # the writer is the same code that produced them.
    return properties


__all__ = [
    "compute_content_hash",
    "compute_source_key",
]

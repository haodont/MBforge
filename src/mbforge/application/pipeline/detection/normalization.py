"""Normalize and deduplicate extracted molecule candidates.

Validates SMILES through RDKit, canonicalizes valid structures, and merges
duplicate detections into ``Molecule`` records consumed by the
persistence and Markush review stages.

``Molecule`` is the shared molecule entity between the pipeline and core;
``DetectionSource`` and ``ExtractionResult`` remain raw observation records.
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem

from mbforge.domain.molecule import Molecule
from mbforge.domain.types import (
    DetectionSource,
    ExtractionResult,
)
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.detection.normalization")

# Default set of allowed chemical elements for normalized molecules.
#
# This whitelist intentionally excludes most metals and heavy/main-group elements
# because the current pipeline (MolParser + library) is tuned for small
# organic / drug-like molecules. Organometallic or inorganic structures that
# contain Re, Rf, Pb, Hg, etc. are rejected rather than silently imported with
# likely misread R-group labels. Callers can override this behavior by passing
# a custom ``allowed_elements`` set to :func:`normalize_molecules`.
DEFAULT_ALLOWED_ELEMENTS = {
    "C",
    "N",
    "O",
    "S",
    "F",
    "Cl",
    "Br",
    "I",
    "P",
    "B",
    "Si",
    "Se",
    "As",
    "H",
    "*",
}


def _detection_from_result(r: ExtractionResult) -> DetectionSource:
    """Build a DetectionSource from an ExtractionResult."""
    return DetectionSource(
        source="image",
        page=r.page_idx,
        bbox=r.bbox_pdf,
        image_path=(r.mol_img_path.replace("\\", "/") if r.mol_img_path else None),
        confidence=r.moldet_conf,
        conf_moldet=r.moldet_conf,
    )


def _structure_fields(result: ExtractionResult) -> tuple[str, bool, str, str]:
    """Return Layer 1 plus the optional Markush payload.

    MolParser image results provide Layer 1 explicitly in ``smiles``.
    """
    raw = result.smiles.strip()
    metadata = result.properties
    markush = isinstance(metadata, dict) and metadata.get("markush") is True
    esmiles = result.esmiles.strip() if markush else ""
    groups = (
        metadata.get("groups", "") if markush and isinstance(metadata, dict) else ""
    )
    if not isinstance(groups, str):
        groups = ""
    return raw, markush, esmiles, groups


def _identity_key(
    canonical_smiles: str,
    *,
    markush: bool,
    esmiles: str,
    groups: str,
) -> tuple[str, ...]:
    if markush:
        return ("markush", canonical_smiles, esmiles, groups)
    return ("normal", canonical_smiles)


def _append_detection_metadata(
    properties: dict[str, Any], result: ExtractionResult
) -> None:
    """Preserve labels that may disambiguate Markush from concrete structures.

    The canonical SMILES is not enough for this decision: a generic drawing
    can be misread as a valid closed SMILES.  Keep the small textual signals
    supplied by OCR/coreference extraction when equivalent SMILES are merged.

    For ``formula_label`` and ``label`` keys we additionally run the raw
    value through :func:`label_normalization.normalize_coref_label` and store
    the canonical ``raw_coref_label`` / ``normalized_label`` / ``label_kind``
    triple directly on ``properties``. Downstream persistence reads these
    fields; the legacy ``formula_label`` / ``label`` keys are still written
    for back-compat with readers that are keyed on them.
    """
    if result.name:
        names: list[str] = properties.setdefault("detection_names", [])
        if result.name not in names:
            names.append(result.name)
        # Track each distinct name with the highest detection confidence it
        # was seen at, so :func:`select_molecule_name` can rank candidates
        # deterministically instead of letting input order decide.
        candidates: list[dict[str, Any]] = properties.setdefault("name_candidates", [])
        for candidate in candidates:
            if candidate["name"] == result.name:
                candidate["confidence"] = max(
                    candidate["confidence"], result.moldet_conf
                )
                break
        else:
            candidates.append({"name": result.name, "confidence": result.moldet_conf})
    metadata = result.properties
    if not isinstance(metadata, dict):
        return
    if metadata.get("markush") is True:
        properties["markush"] = True
        groups = metadata.get("groups")
        if isinstance(groups, str):
            properties["groups"] = groups
    # Imported lazily to avoid a circular import at module load time
    # (label_normalization is otherwise dependency-free).
    from mbforge.application.pipeline.detection.label_normalization import (
        LabelKind,
        normalize_coref_label,
    )

    for key in ("formula_label", "label"):
        value = metadata.get(key)
        if not isinstance(value, str):
            continue
        # Preserve the original OCR string in role_contexts so the
        # classifier can still inspect it; the canonical triple goes on
        # top-level properties for persistence.
        contexts: list[str] = properties.setdefault("role_contexts", [])
        if value and value not in contexts:
            contexts.append(value)
        # Back-compat: write the original string under its old key so
        # any reader still keyed on ``formula_label`` / ``label`` keeps
        # working.
        properties[key] = value
        normalized = normalize_coref_label(value)
        if normalized is None:
            # Unknown labels are still recorded for traceability; they
            # just don't contribute a normalized form.
            properties.setdefault("raw_coref_label", value)
            properties.setdefault("label_kind", LabelKind.UNKNOWN.value)
            continue
        # Only overwrite if we have not yet seen a value; later
        # detections of the same molecule must not erase an earlier
        # label — the first non-empty OCR hit is the canonical one.
        if "raw_coref_label" not in properties:
            properties["raw_coref_label"] = normalized.raw
            properties["normalized_label"] = normalized.normalized
            properties["label_kind"] = normalized.kind.value
    for key in ("role_context", "page_context", "caption"):
        value = metadata.get(key)
        if isinstance(value, str):
            contexts = properties.setdefault("role_contexts", [])
            if value and value not in contexts:
                contexts.append(value)
    # Crop-label OCR reads (compound numbers / group formulas from the
    # DBSCAN "others" image): keep them for review and Markush hints.
    labels = metadata.get("ocr_labels")
    if isinstance(labels, list):
        merged_labels: list[str] = properties.setdefault("ocr_labels", [])
        for label in labels:
            if isinstance(label, str) and label and label not in merged_labels:
                merged_labels.append(label)
    # Recommended single identifier: first non-empty suggestion wins
    # (detections merge in order; later suggestions are redundant).
    primary = metadata.get("ocr_labels_primary")
    if isinstance(primary, str) and primary:
        properties.setdefault("ocr_labels_primary", primary)


def select_molecule_name(
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Deterministically pick the best name from merged candidates.

    Candidates are ``{"name": str, "confidence": float}`` dicts in the order
    they were first detected. Ranking rules, highest priority first:

    1. Names that normalize to a compound/example label.
    2. Non-empty names that pass label normalization (any other kind).
    3. Any other non-empty name.

    Within a tier the higher detection confidence wins; remaining ties are
    broken by the original candidate order, so the result never depends on
    dictionary or input ordering beyond first-detection order.

    Returns a selection record ``{"name", "rule", "confidence"}`` suitable
    for storing on ``Molecule.properties``, or ``None`` when there
    are no candidates.
    """
    if not candidates:
        return None
    # Imported lazily to avoid a circular import at module load time
    # (label_normalization is otherwise dependency-free).
    from mbforge.application.pipeline.detection.label_normalization import (
        LabelKind,
        normalize_coref_label,
    )

    def _rank(indexed: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
        index, candidate = indexed
        normalized = normalize_coref_label(candidate["name"])
        if normalized is not None and normalized.kind in (
            LabelKind.COMPOUND,
            LabelKind.EXAMPLE,
        ):
            tier = 0
        elif normalized is not None:
            tier = 1
        else:
            tier = 2
        return (tier, -float(candidate.get("confidence", 0.0)), index)

    best = min(enumerate(candidates), key=_rank)
    tier = _rank(best)[0]
    rule = (
        "normalized_compound_label",
        "normalized_label",
        "non_empty_name",
    )[tier]
    candidate = best[1]
    return {
        "name": candidate["name"],
        "rule": rule,
        "confidence": candidate.get("confidence", 0.0),
    }


def _merge_detection(existing: Molecule, r: ExtractionResult) -> None:
    """Append a detection to an existing molecule and keep it sorted."""
    existing.detections.append(_detection_from_result(r))
    existing.detections.sort(key=lambda d: d.confidence, reverse=True)
    _append_detection_metadata(existing.properties, r)


def normalize_molecules(
    results: list[ExtractionResult],
    *,
    allowed_elements: set[str] | None = None,
) -> list[Molecule]:
    """Validate SMILES, canonicalize, and deduplicate candidates.

    Valid molecules are keyed by Layer-1 canonical SMILES for normal molecules,
    and by Layer-1 plus the original Markush E-SMILES/groups for Markush
    molecules. Invalid records use the same identity shape with their raw
    Layer-1 value.

    Args:
        results: Extraction results from MolParser / text extraction.
        allowed_elements: Optional override for the element whitelist. When
            ``None``, :data:`DEFAULT_ALLOWED_ELEMENTS` is used. Pass a broader
            set (e.g. including ``"Fe"``, ``"Pt"``) to accept organometallic
            or inorganic structures.
    """
    by_canonical: dict[tuple[str, ...], Molecule] = {}
    by_invalid: dict[tuple[str, ...], Molecule] = {}

    # Pre-filter only for clearly unusable fragments. We do NOT reject SMILES
    # containing ``*`` here — ``*`` is a valid Markush wildcard atom (used by
    # patent R-group definitions) and is exactly what MolParser emits for
    # markush structures. RDKit can parse and round-trip Markush SMILES, so
    # let it be the authoritative gate.
    def _is_unusable_fragment(smiles: str) -> bool:
        if not smiles or len(smiles) < 3:
            return True
        # pure numeric (no atoms at all) — clearly garbage
        return bool(smiles.isdigit())

    for r in results:
        raw, markush, original_esmiles, groups = _structure_fields(r)
        stored_esmiles = original_esmiles if markush else raw
        identity = _identity_key(
            raw,
            markush=markush,
            esmiles=original_esmiles,
            groups=groups,
        )
        if _is_unusable_fragment(raw):
            logger.debug("Rejected low-quality SMILES: %s", raw)
            if identity in by_invalid:
                _merge_detection(by_invalid[identity], r)
            else:
                properties: dict[str, Any] = {}
                _append_detection_metadata(properties, r)
                by_invalid[identity] = Molecule(
                    canonical_smiles=raw,
                    esmiles=stored_esmiles,
                    name=r.name,
                    sources=["image"],
                    detections=[_detection_from_result(r)],
                    status="rejected",
                    reject_reason="low_quality_smiles",
                    properties=properties,
                )
            continue

        try:
            mol = Chem.MolFromSmiles(raw)
        except Exception as exc:
            logger.debug("RDKit error for %r: %s", raw, exc)
            mol = None

        if mol is None:
            logger.debug("Rejected invalid SMILES: %s", raw)
            if identity in by_invalid:
                _merge_detection(by_invalid[identity], r)
            else:
                properties: dict[str, Any] = {}
                _append_detection_metadata(properties, r)
                by_invalid[identity] = Molecule(
                    canonical_smiles=raw,
                    esmiles=stored_esmiles,
                    name=r.name,
                    sources=["image"],
                    detections=[_detection_from_result(r)],
                    status="rejected",
                    reject_reason="invalid_smiles",
                    properties=properties,
                )
            continue

        # Element whitelist — RDKit accepts some rare elements that have
        # no place in a drug-like molecule library (e.g. ``[Re]`` for Rhenium,
        # ``[Rf]`` for Rutherfordium). These are almost always MolParser
        # mis-reading R-group subscripts (Rₑ / R_f). Treat as garbage.
        # The whitelist is configurable via ``allowed_elements`` so callers
        # can opt-in to organometallic/inorganic structures.
        allowed = (
            allowed_elements
            if allowed_elements is not None
            else DEFAULT_ALLOWED_ELEMENTS
        )
        invalid_atoms = [
            a.GetSymbol() for a in mol.GetAtoms() if a.GetSymbol() not in allowed
        ]
        if invalid_atoms:
            logger.debug(
                "Rejected SMILES with non-chemistry elements %s: %s",
                invalid_atoms,
                raw,
            )
            if identity in by_invalid:
                _merge_detection(by_invalid[identity], r)
            else:
                properties = {}
                _append_detection_metadata(properties, r)
                by_invalid[identity] = Molecule(
                    canonical_smiles=raw,
                    esmiles=stored_esmiles,
                    name=r.name,
                    sources=["image"],
                    detections=[_detection_from_result(r)],
                    status="rejected",
                    reject_reason="invalid_element",
                    properties=properties,
                )
            continue

        try:
            canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        except Exception as exc:
            logger.debug("RDKit canonicalization error for %r: %s", raw, exc)
            if identity in by_invalid:
                _merge_detection(by_invalid[identity], r)
            else:
                properties = {}
                _append_detection_metadata(properties, r)
                by_invalid[identity] = Molecule(
                    canonical_smiles=raw,
                    esmiles=stored_esmiles,
                    name=r.name,
                    sources=["image"],
                    detections=[_detection_from_result(r)],
                    status="rejected",
                    reject_reason="canonicalization_failed",
                    properties=properties,
                )
            continue

        identity = _identity_key(
            canonical,
            markush=markush,
            esmiles=original_esmiles,
            groups=groups,
        )
        if identity in by_canonical:
            _merge_detection(by_canonical[identity], r)
        else:
            properties = {}
            _append_detection_metadata(properties, r)
            by_canonical[identity] = Molecule(
                canonical_smiles=canonical,
                esmiles=stored_esmiles,
                name=r.name,
                sources=["image"],
                detections=[_detection_from_result(r)],
                status="pending",
                properties=properties,
            )

    normalized = list(by_canonical.values()) + list(by_invalid.values())
    for molecule in normalized:
        # Re-select the merged name deterministically: the first detection's
        # name must not permanently override a better label seen later.
        selection = select_molecule_name(molecule.properties.get("name_candidates", []))
        if selection is not None:
            molecule.name = selection["name"]
            molecule.properties["name_selection"] = selection
    return normalized

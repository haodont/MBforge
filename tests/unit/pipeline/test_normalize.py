"""Unit tests for molecule normalization and deduplication.

Covers ``mbforge.service.pipeline.detection.normalization.normalize_molecules``:
Layer-1 canonical-SMILES deduplication, rejection reasons, the configurable
element whitelist, name selection and metadata merging.
"""

from __future__ import annotations

from mbforge.domain.types import ExtractionResult
from mbforge.service.pipeline.detection.normalization import normalize_molecules


def test_canonical_smiles_dedup_merges_detections_sorted_by_confidence() -> None:
    """Equivalent SMILES collapse to one record; distinct ones stay separate,
    and merged detections are ordered by the MolDet score."""
    equivalent = [
        ExtractionResult(smiles="CCO", esmiles="CCO"),
        ExtractionResult(smiles="OCC", esmiles="OCC"),
    ]

    normalized = normalize_molecules(equivalent)
    assert len(normalized) == 1
    assert normalized[0].canonical_smiles == "CCO"
    assert set(normalized[0].sources) == {"image"}
    assert normalized[0].status == "pending"

    distinct = [
        ExtractionResult(smiles="CCO", esmiles="CCO"),
        ExtractionResult(smiles="c1ccccc1", esmiles="c1ccccc1"),
    ]

    normalized = normalize_molecules(distinct)
    assert len(normalized) == 2
    assert {m.canonical_smiles for m in normalized} == {"CCO", "c1ccccc1"}

    merged = normalize_molecules(
        [
            ExtractionResult(smiles="CCO", esmiles="CCO", moldet_conf=0.5),
            ExtractionResult(smiles="CCO", esmiles="CCO", moldet_conf=0.9),
        ]
    )
    assert len(merged) == 1
    assert len(merged[0].detections) == 2
    assert merged[0].detections[0].confidence == 0.9
    assert merged[0].detections[1].confidence == 0.5
    # DetectionSource keeps the MolDet score used for ordering.
    assert merged[0].detections[0].conf_moldet == 0.9


def test_invalid_low_quality_and_non_chemistry_structures_are_rejected() -> None:
    """Unparseable, too-short and OCR-element candidates are rejected with a
    stable reason; the element whitelist stays configurable."""
    invalid = normalize_molecules(
        [ExtractionResult(smiles="not_a_smiles", esmiles="not_a_smiles")]
    )
    assert len(invalid) == 1
    assert invalid[0].status == "rejected"
    assert invalid[0].reject_reason == "invalid_smiles"

    low_quality = normalize_molecules(
        [
            ExtractionResult(smiles="C", esmiles="C"),
            ExtractionResult(smiles="12345", esmiles="12345"),
        ]
    )
    assert len(low_quality) == 2
    assert all(m.status == "rejected" for m in low_quality)
    assert all(m.reject_reason == "low_quality_smiles" for m in low_quality)

    # Symbols like [Re] are almost always OCR errors.
    elements = normalize_molecules([ExtractionResult(smiles="[Re]C", esmiles="[Re]C")])
    assert len(elements) == 1
    assert elements[0].status == "rejected"
    assert elements[0].reject_reason == "invalid_element"

    iron = [ExtractionResult(smiles="[Fe]C", esmiles="[Fe]C")]
    default_normalized = normalize_molecules(iron)
    assert default_normalized[0].status == "rejected"
    assert default_normalized[0].reject_reason == "invalid_element"

    custom_normalized = normalize_molecules(iron, allowed_elements={"C", "Fe", "H"})
    assert custom_normalized[0].status == "pending"


def test_layer1_is_authoritative_and_markush_metadata_survives_the_merge() -> None:
    """Layer 1 wins over E-SMILES extensions; generic payload stays internal
    while role-relevant labels survive canonical-SMILES deduplication."""
    normal = ExtractionResult(
        smiles="CCO",
        esmiles="CCO<sep>ignored-normal-extension",
        properties={"markush": False, "sru": True, "groups": "ignored"},
    )
    markush = ExtractionResult(
        smiles="CCO",
        esmiles="CCO<sep>R1-definition",
        properties={"markush": True, "sru": True, "groups": "R1=alkyl"},
    )

    normalized = normalize_molecules([normal, markush])

    assert len(normalized) == 2
    ordinary = next(item for item in normalized if not item.properties.get("markush"))
    generic = next(item for item in normalized if item.properties.get("markush"))
    assert ordinary.canonical_smiles == "CCO"
    assert ordinary.esmiles == "CCO"
    assert "groups" not in ordinary.properties
    assert "sru" not in ordinary.properties
    assert generic.esmiles == "CCO<sep>R1-definition"
    assert generic.properties == {"markush": True, "groups": "R1=alkyl"}

    labelled = normalize_molecules(
        [
            ExtractionResult(smiles="OCC", esmiles="OCC", name="R1"),
            ExtractionResult(
                smiles="CCO",
                esmiles="CCO",
                properties={"formula_label": "Formula I"},
            ),
        ]
    )
    assert len(labelled) == 1
    assert labelled[0].properties["detection_names"] == ["R1"]
    assert labelled[0].properties["role_contexts"] == ["Formula I"]


def test_name_selection_prefers_labels_then_confidence_then_first_detection() -> None:
    """A normalized compound label outranks a recognized label, then a plain
    name; ties fall back to confidence and first-detection order."""
    first = [
        ExtractionResult(smiles="CCO", esmiles="CCO", name="the title compound"),
        ExtractionResult(smiles="OCC", esmiles="OCC", name="3a"),
    ]
    reversed_order = list(reversed(first))

    for candidates in (first, reversed_order):
        normalized = normalize_molecules(candidates)
        assert len(normalized) == 1
        assert normalized[0].name == "3a"
        selection = normalized[0].properties["name_selection"]
        assert selection["rule"] == "normalized_compound_label"
        assert set(normalized[0].properties["detection_names"]) == {
            "the title compound",
            "3a",
        }

    recognized = normalize_molecules(
        [
            ExtractionResult(smiles="CCO", esmiles="CCO", name="compound abc"),
            ExtractionResult(smiles="OCC", esmiles="OCC", name="R1"),
        ]
    )
    assert recognized[0].name == "R1"
    assert recognized[0].properties["name_selection"]["rule"] == "normalized_label"

    # Within one tier the higher MolDet confidence wins.
    confident = normalize_molecules(
        [
            ExtractionResult(smiles="CCO", esmiles="CCO", name="3a", moldet_conf=0.4),
            ExtractionResult(smiles="OCC", esmiles="OCC", name="12b", moldet_conf=0.9),
        ]
    )
    assert confident[0].name == "12b"
    assert confident[0].properties["name_selection"]["rule"] == (
        "normalized_compound_label"
    )
    assert confident[0].properties["name_selection"]["confidence"] == 0.9

    # Equal tier and confidence fall back to first-detection order.
    tied = normalize_molecules(
        [
            ExtractionResult(smiles="CCO", esmiles="CCO", name="3a", moldet_conf=0.5),
            ExtractionResult(smiles="OCC", esmiles="OCC", name="12b", moldet_conf=0.5),
        ]
    )
    assert tied[0].name == "3a"

    # Molecules without any name candidate keep the empty name.
    unnamed = normalize_molecules(
        [
            ExtractionResult(smiles="CCO", esmiles="CCO"),
            ExtractionResult(smiles="OCC", esmiles="OCC"),
        ]
    )
    assert unnamed[0].name == ""
    assert "name_selection" not in unnamed[0].properties


def test_ocr_labels_merge_in_detection_order_without_duplicates() -> None:
    """Crop-label OCR reads merge deduplicated; malformed payloads never crash."""
    candidates = [
        ExtractionResult(
            smiles="CCO",
            esmiles="CCO",
            properties={"ocr_labels": ["4A", "CF3"]},
        ),
        ExtractionResult(
            smiles="OCC",
            esmiles="OCC",
            properties={"ocr_labels": ["CF3", "8b"]},
        ),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert normalized[0].properties["ocr_labels"] == ["4A", "CF3", "8b"]

    malformed = [
        ExtractionResult(
            smiles="CCO",
            esmiles="CCO",
            properties={"ocr_labels": "not-a-list"},
        ),
        ExtractionResult(
            smiles="CCO",
            esmiles="CCO",
            properties={"ocr_labels": ["4A", 42, None]},
        ),
    ]

    normalized = normalize_molecules(malformed)
    assert len(normalized) == 1
    assert normalized[0].properties["ocr_labels"] == ["4A"]

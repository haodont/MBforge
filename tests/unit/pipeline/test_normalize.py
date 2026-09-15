"""Unit tests for molecule normalization and deduplication."""

from __future__ import annotations

from mbforge.core.types import ExtractionResult
from mbforge.pipeline.detection.normalization import normalize_molecules


def test_normalize_deduplicates_equivalent_smiles() -> None:
    """CCO, OCC, and C-C-O should all canonicalize to the same molecule."""
    candidates = [
        ExtractionResult(esmiles="CCO", source="text", status="pending"),
        ExtractionResult(esmiles="OCC", source="text", status="pending"),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert normalized[0].canonical_smiles == "CCO"
    assert set(normalized[0].sources) == {"text"}
    assert normalized[0].status == "pending"


def test_normalize_keeps_image_and_text_sources_separate() -> None:
    """Two different molecules should produce two Molecule records."""
    candidates = [
        ExtractionResult(esmiles="CCO", source="text", status="pending"),
        ExtractionResult(
            esmiles="c1ccccc1", smiles="c1ccccc1", source="image", status="pending"
        ),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 2
    canonicals = {m.canonical_smiles for m in normalized}
    assert canonicals == {"CCO", "c1ccccc1"}


def test_normalize_rejects_invalid_smiles() -> None:
    """Garbage strings that RDKit cannot parse become rejected records."""
    candidates = [
        ExtractionResult(esmiles="not_a_smiles", source="text", status="pending"),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert normalized[0].status == "rejected"
    assert normalized[0].reject_reason == "invalid_smiles"


def test_normalize_rejects_low_quality_fragments() -> None:
    """Single characters or pure digits are rejected as low quality."""
    candidates = [
        ExtractionResult(esmiles="C", source="text", status="pending"),
        ExtractionResult(esmiles="12345", source="text", status="pending"),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 2
    assert all(m.status == "rejected" for m in normalized)
    assert all(m.reject_reason == "low_quality_smiles" for m in normalized)


def test_normalize_rejects_non_chemistry_elements() -> None:
    """Symbols like [Re] are almost always OCR errors and should be rejected."""
    candidates = [
        ExtractionResult(
            esmiles="[Re]C", smiles="[Re]C", source="image", status="pending"
        ),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert normalized[0].status == "rejected"
    assert normalized[0].reject_reason == "invalid_element"


def test_normalize_merges_detections_sorted_by_confidence() -> None:
    """Duplicate canonical SMILES merge detections, highest confidence first."""
    candidates = [
        ExtractionResult(
            esmiles="CCO",
            smiles="CCO",
            source="image",
            moldet_conf=0.5,
            status="pending",
        ),
        ExtractionResult(
            esmiles="CCO",
            smiles="CCO",
            source="image",
            moldet_conf=0.9,
            status="pending",
        ),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert len(normalized[0].detections) == 2
    assert normalized[0].detections[0].confidence == 0.9
    assert normalized[0].detections[1].confidence == 0.5


def test_normalize_allowed_elements_is_configurable() -> None:
    """Passing a custom allowed_elements set accepts otherwise-rejected atoms."""
    candidates = [
        ExtractionResult(
            esmiles="[Fe]C", smiles="[Fe]C", source="image", status="pending"
        ),
    ]

    # Default whitelist rejects Fe.
    default_normalized = normalize_molecules(candidates)
    assert default_normalized[0].status == "rejected"
    assert default_normalized[0].reject_reason == "invalid_element"

    # Custom whitelist accepts Fe.
    custom_normalized = normalize_molecules(
        candidates, allowed_elements={"C", "Fe", "H"}
    )
    assert custom_normalized[0].status == "pending"


def test_normalize_carries_moldet_confidence() -> None:
    """DetectionSource keeps the MolDet score used for ordering."""
    candidates = [
        ExtractionResult(
            esmiles="CCO",
            smiles="CCO",
            source="image",
            moldet_conf=0.9,
            status="pending",
        ),
    ]

    normalized = normalize_molecules(candidates)
    detection = normalized[0].detections[0]
    assert detection.conf_moldet == 0.9
    assert detection.confidence == 0.9


def test_normalize_uses_layer1_and_keeps_markush_payload_separate() -> None:
    """Layer 1 is authoritative; Markush E-SMILES/groups remain internal metadata."""
    normal = ExtractionResult(
        esmiles="CCO<sep>ignored-normal-extension",
        smiles="CCO",
        source="image",
        properties={"markush": False, "sru": True, "groups": "ignored"},
    )
    markush = ExtractionResult(
        esmiles="CCO<sep>R1-definition",
        smiles="CCO",
        source="image",
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


def test_normalize_preserves_markush_context_metadata_after_merge() -> None:
    """Role-relevant labels survive canonical-SMILES deduplication."""
    candidates = [
        ExtractionResult(esmiles="OCC", smiles="OCC", source="image", name="R1"),
        ExtractionResult(
            esmiles="CCO",
            source="text",
            properties={"formula_label": "Formula I"},
        ),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert normalized[0].properties["detection_names"] == ["R1"]
    assert normalized[0].properties["role_contexts"] == ["Formula I"]


def test_normalize_prefers_compound_label_over_plain_name() -> None:
    """A normalized compound label beats an unrecognized name, any order."""
    first = [
        ExtractionResult(esmiles="CCO", source="text", name="the title compound"),
        ExtractionResult(esmiles="OCC", source="text", name="3a"),
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


def test_normalize_prefers_recognized_label_over_plain_name() -> None:
    """Recognizable labels outrank names that fail label normalization."""
    candidates = [
        ExtractionResult(esmiles="CCO", source="text", name="compound abc"),
        ExtractionResult(esmiles="OCC", source="text", name="R1"),
    ]

    normalized = normalize_molecules(candidates)
    assert normalized[0].name == "R1"
    assert normalized[0].properties["name_selection"]["rule"] == "normalized_label"


def test_normalize_same_tier_picks_higher_detection_confidence() -> None:
    """Within one tier, the higher MolDet confidence wins."""
    candidates = [
        ExtractionResult(esmiles="CCO", source="image", name="3a", moldet_conf=0.4),
        ExtractionResult(esmiles="OCC", source="image", name="12b", moldet_conf=0.9),
    ]

    normalized = normalize_molecules(candidates)
    assert normalized[0].name == "12b"
    selection = normalized[0].properties["name_selection"]
    assert selection["rule"] == "normalized_compound_label"
    assert selection["confidence"] == 0.9


def test_normalize_same_tier_tie_keeps_first_detection_order() -> None:
    """Equal tier and confidence fall back to first-detection order."""
    candidates = [
        ExtractionResult(esmiles="CCO", source="image", name="3a", moldet_conf=0.5),
        ExtractionResult(esmiles="OCC", source="image", name="12b", moldet_conf=0.5),
    ]

    normalized = normalize_molecules(candidates)
    assert normalized[0].name == "3a"


def test_normalize_without_names_records_no_selection() -> None:
    """Molecules without any name candidate keep the empty name."""
    candidates = [
        ExtractionResult(esmiles="CCO", smiles="CCO", source="image"),
        ExtractionResult(esmiles="OCC", smiles="OCC", source="image"),
    ]

    normalized = normalize_molecules(candidates)
    assert normalized[0].name == ""
    assert "name_selection" not in normalized[0].properties


def test_normalize_merges_ocr_labels_deduplicated() -> None:
    """Crop-label OCR reads merge in detection order without duplicates."""
    candidates = [
        ExtractionResult(
            esmiles="CCO",
            smiles="CCO",
            source="image",
            properties={"ocr_labels": ["4A", "CF3"]},
        ),
        ExtractionResult(
            esmiles="OCC",
            smiles="OCC",
            source="image",
            properties={"ocr_labels": ["CF3", "8b"]},
        ),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert normalized[0].properties["ocr_labels"] == ["4A", "CF3", "8b"]


def test_normalize_ignores_malformed_ocr_labels() -> None:
    """Non-list or non-string ocr_labels payloads never crash the merge."""
    candidates = [
        ExtractionResult(
            esmiles="CCO",
            smiles="CCO",
            source="image",
            properties={"ocr_labels": "not-a-list"},
        ),
        ExtractionResult(
            esmiles="CCO",
            smiles="CCO",
            source="image",
            properties={"ocr_labels": ["4A", 42, None]},
        ),
    ]

    normalized = normalize_molecules(candidates)
    assert len(normalized) == 1
    assert normalized[0].properties["ocr_labels"] == ["4A"]

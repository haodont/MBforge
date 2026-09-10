from __future__ import annotations

import pytest

from mbforge.core.evidence import SourceEvidence


def test_source_evidence_id_is_position_based_and_round_trips() -> None:
    first = SourceEvidence.create(
        doc_id="doc",
        page=1,
        bbox=(1.234, 2.0, 10.0, 20.0),
        raw_text="first",
    )
    same_position = SourceEvidence.create(
        doc_id="doc",
        page=1,
        bbox=(1.2344, 2.0, 10.0, 20.0),
        raw_text="changed",
    )
    different_position = SourceEvidence.create(
        doc_id="doc",
        page=1,
        bbox=(1.24, 2.0, 10.0, 20.0),
        raw_text="first",
    )

    assert first.evidence_id == same_position.evidence_id
    assert first.evidence_id != different_position.evidence_id
    assert SourceEvidence.from_dict(first.to_dict()) == first


def test_source_evidence_requires_content_and_valid_bbox() -> None:
    with pytest.raises(TypeError, match="bbox"):
        SourceEvidence.create(doc_id="doc", page=1, raw_text="text")

    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.create(
            doc_id="doc",
            page=1,
            bbox=None,
            raw_text="text",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="raw_text or coref"):
        SourceEvidence.create(doc_id="doc", page=1, bbox=(0.0, 0.0, 1.0, 1.0))

    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.from_dict({"doc_id": "doc", "page": 1, "raw_text": "legacy"})

    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.create(
            doc_id="doc",
            page=1,
            bbox=(10.0, 0.0, 1.0, 1.0),
            raw_text="text",
        )

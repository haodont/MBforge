"""Unit tests for :class:`mbforge.domain.evidence.SourceEvidence`."""

from __future__ import annotations

import pytest

from mbforge.domain.evidence import SourceEvidence


def test_source_evidence_create_derives_position_id_and_validates_input() -> None:
    """``evidence_id`` is derived from the quantized position (so re-OCR of a
    moved-by-less-than-quantum bbox keeps identity) and round-trips through
    ``to_dict``/``from_dict``; content-less or bbox-less evidence is refused."""
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

    with pytest.raises(TypeError, match="bbox"):
        SourceEvidence.create(doc_id="doc", page=1, raw_text="text")

    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.create(
            doc_id="doc",
            page=1,
            bbox=None,
            raw_text="text",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.from_dict({"doc_id": "doc", "page": 1, "raw_text": "legacy"})

    with pytest.raises(ValueError, match="bbox"):
        SourceEvidence.create(
            doc_id="doc",
            page=1,
            bbox=(10.0, 0.0, 1.0, 1.0),
            raw_text="text",
        )

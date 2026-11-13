"""A caption naming several designations is a declared limitation, not a backlog item.

Marks: ``mbforge.db.measurement_store.group_caption_designations`` and
``mbforge.service.use_cases.documents.activity_queries._unattributed_reason``.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.domain.evidence import SourceEvidence
from mbforge.db.measurement_store import group_caption_designations
from mbforge.db.source_evidence import persist_source_evidence
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.service.use_cases.documents.activity_queries import _unattributed_reason


def _evidence(doc_id: str, text: str, page: int) -> SourceEvidence:
    return SourceEvidence(
        evidence_id=f"ev-{page}-{abs(hash(text)) % 99999}",
        doc_id=doc_id,
        page=page,
        kind="figno",
        raw_text=text,
        bbox=(10.0, 20.0, 30.0, 40.0),
    )


def test_a_caption_that_names_a_stereoisomer_family_is_its_own_reason(
    tmp_path: Path,
) -> None:
    """CN120943813A prints ``1-P2 or 1-P1 or 1-P3 or 1-P4`` under four drawings.

    The document drew all four stereoisomers, but one caption names the set, so no
    structure is printed *for* one designation. Reporting that as ``label_not_read``
    would hide a declared limitation behind recoverable extraction work.
    """
    DatabaseManager.get(str(tmp_path)).initialize()
    persist_source_evidence(
        str(tmp_path),
        [
            _evidence("doc-1", "1-P2 or 1-P1 or 1-P3 or 1-P4", 50),
            _evidence("doc-1", "I-233-A、I-233-B、I-233-C、I-233-D中的一个或两个", 162),
            _evidence("doc-1", "I-2", 195),
        ],
    )

    grouped = group_caption_designations(str(tmp_path), "doc-1")

    assert {"1-P1", "1-P2", "1-P3", "1-P4"} <= grouped
    assert {"I-233-A", "I-233-B", "I-233-C", "I-233-D"} <= grouped
    # A designation printed on its own is not part of a group caption.
    assert "I-2" not in grouped

    assert (
        _unattributed_reason("1-P2", set(), 3, 40, grouped)
        == "designation_group_caption"
    )
    # A structure that carries the designation is still the stronger statement.
    assert (
        _unattributed_reason("1-P2", {"1-P2"}, 3, 40, grouped)
        == "structure_detected_unmatched"
    )
    assert _unattributed_reason("I-2", set(), 3, 40, grouped) == "label_not_read"

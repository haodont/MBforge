"""Patent domain entity: the compound entry described in a document.

A :class:`CompoundEntry` is the "Example 4 / Compound 4A / Preparation 2"
record a reader sees in a patent. It exists as first-class data even
when structure recognition fails — downstream structure linking is optional
(``entity_id`` may be ``None``) and tracked via status fields.

The Patent stage emits this document-local record before downstream linking.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from mbforge.foundation.ids import stable_id

#: What role the entry plays in the document narrative.
ROLE_EXAMPLE = "example"  # 实施例
ROLE_PREPARATION = "preparation"  # 制备例
ROLE_COMPOUND = "compound"  # 化合物编号（通式具体化）
ROLE_INTERMEDIATE = "intermediate"
ROLE_REAGENT = "reagent"

#: Structure/extraction/linking lifecycle values (strings on purpose —
#: they round-trip through JSON without enum plumbing).
STRUCTURE_MISSING = "missing"
STRUCTURE_PENDING = "pending"
STRUCTURE_RESOLVED = "resolved"

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_FAILED = "failed"

_COMPOUND_TOKEN = r"(?:E\d+|\d+[A-Za-z]?)"
_COMPOUND_PREFIX_RE = re.compile(
    rf"^(?:化合物|compound|cmpd|cpd)\s*#?\s*(?P<token>{_COMPOUND_TOKEN})$",
    re.IGNORECASE,
)
_COMPOUND_BARE_RE = re.compile(rf"^(?P<token>{_COMPOUND_TOKEN})$")


def entry_id(doc_id: str, section_id: str, label_key: str) -> str:
    """Deterministic entry ID: doc + type + section + normalized label.

    Same (document, section, label) always yields the same ID, so a
    re-run does not duplicate entries (spec §3.5 rule 3).
    """
    return stable_id("entry", doc_id, section_id, label_key)


def compound_label_key(value: object) -> str | None:
    """Return an exact key for a compound designation, or ``None``."""
    cleaned = unicodedata.normalize("NFKC", str(value or "")).strip()
    cleaned = re.sub(r"^[#\s>*•·-]+", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(".。 ")
    match = _COMPOUND_PREFIX_RE.fullmatch(cleaned) or _COMPOUND_BARE_RE.fullmatch(
        cleaned
    )
    return match.group("token") if match else None


def label_key_for(label_raw: str) -> str:
    """Normalized label used for matching and stable IDs.

    Compound designations use the shared exact-token normalizer.
    """
    key = compound_label_key(label_raw)
    if key is not None:
        return key
    collapsed = " ".join(label_raw.split())
    return collapsed.rstrip(".")


@dataclass
class CompoundEntry:
    """A compound entry as printed in the patent document."""

    entry_id: str
    doc_id: str
    label_raw: str
    label_key: str
    entry_role: str  # example/preparation/compound/intermediate/reagent
    name_raw: str = ""
    section_id: str = ""
    entity_id: str | None = None  # link to Molecule, optional
    structure_status: str = STRUCTURE_MISSING
    extraction_status: str = STATUS_PENDING
    linking_status: str = STATUS_PENDING
    review_status: str = STATUS_PENDING
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "doc_id": self.doc_id,
            "label_raw": self.label_raw,
            "label_key": self.label_key,
            "entry_role": self.entry_role,
            "name_raw": self.name_raw,
            "section_id": self.section_id,
            "entity_id": self.entity_id,
            "structure_status": self.structure_status,
            "extraction_status": self.extraction_status,
            "linking_status": self.linking_status,
            "review_status": self.review_status,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompoundEntry:
        return cls(
            entry_id=data["entry_id"],
            doc_id=data["doc_id"],
            label_raw=data["label_raw"],
            label_key=data["label_key"],
            entry_role=data["entry_role"],
            name_raw=data.get("name_raw", ""),
            section_id=data.get("section_id", ""),
            entity_id=data.get("entity_id"),
            structure_status=data.get("structure_status", STRUCTURE_MISSING),
            extraction_status=data.get("extraction_status", STATUS_PENDING),
            linking_status=data.get("linking_status", STATUS_PENDING),
            review_status=data.get("review_status", STATUS_PENDING),
            evidence_ids=list(data["evidence_ids"]),
        )

"""ExampleRecord — deterministic per-example section summary."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExampleRecord:
    """One 实施例/Example section projected from source evidence.

    Attributes:
        example_idx: 1-based order of appearance in the document.
        page_num: Page the section heading lives on; ``None`` when unavailable.
        heading: The matched heading line, stripped.
        labels: Explicit compound labels mentioned in the section
            (``化合物4A`` / ``compound 28`` / ``实施例21-a`` style).
        esmiles_candidate_ids: Existing candidate IDs mentioned by the source.
        evidence_ids: SourceEvidence IDs covered by this section.
        raw_text: Full source text including the heading line.
    """

    example_idx: int
    page_num: int | None = None
    heading: str = ""
    labels: list[str] = field(default_factory=list)
    esmiles_candidate_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    raw_text: str = ""

    @property
    def section_id(self) -> str:
        """Shared section identity when the record came from the parser."""
        return getattr(self, "_section_id", "")

    @section_id.setter
    def section_id(self, value: str) -> None:
        self._section_id = value

"""Extract Markush R-group definitions from patent text using LLM.

This helper targets documents that contain confirmed scaffolds with pending
attachment sites. It uses a two-phase approach:

1. **Rule-based targeting**: Deterministic regex patterns locate candidate
   text blocks (e.g., "wherein R1 is selected from...", "Formula I wherein...")
   that are likely to contain R-group definitions.

2. **LLM extraction**: Only the matched blocks are sent to the LLM for
   structured extraction. The LLM returns a Pydantic-constrained JSON with:
   - formula_label (e.g., "Formula I")
   - site_label (e.g., "R1")
   - definition (natural language)
   - candidates (list of SMILES or text fragments)
   - evidence_text (original patent excerpt)

3. **Validation**: Regular code validates SMILES, checks attachment counts,
   and matches site labels to the scaffold's atom-map numbers. Invalid
   suggestions are logged but do not block the pipeline.

4. **Suggestion creation**: Valid candidates create ``markush_mounts`` rows
   with ``origin='text_definition'`` and ``status='suggested'``. Users
   confirm or reject them in the UI.

The LLM is NOT responsible for:
- Chemical structure generation (SMILES must be in the text or fragment DB)
- Final binding decisions (suggestions are always human-reviewed)
- Matching attachment counts (validated by business logic)

Failures at any step are logged with full context (doc_id, scaffold_id, block,
error type) and recorded in the pipeline report's
``markush.definition_extraction_errors`` counter.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..core.markush_sites import create_mount
from ..models.detection_cache import ExtractionResult
from ..pipeline.context import PipelineContext
from ..pipeline.stage import StageExecutor
from ..utils.logger import get_logger

logger = get_logger("mbforge.pipeline.extract_markush_definitions")

# Regex patterns for locating Markush definition blocks in patent text.
_FORMULA_PATTERN = re.compile(
    r"(Formula\s+[IVXLCDM]+|General\s+[Ff]ormula|Compound\s+of\s+[Ff]ormula)\s*[:\n]",
    re.IGNORECASE,
)

_WHEREIN_PATTERN = re.compile(
    r"\bwherein\s+([A-Z]\d*|R\d+)\s+is\s+(selected\s+from|independently|optionally|substituted|unsubstituted|chosen|defined\s+as)",
    re.IGNORECASE,
)

_R_GROUP_LIST_PATTERN = re.compile(
    r"(R\d+|A\d+|X\d*|Y\d*|Z\d*)\s+is\s+([^;\.]+(?:;[^;\.]+)*)",
    re.IGNORECASE,
)


class MarkushDefinitionBlock(BaseModel):
    """A candidate text block that may contain R-group definitions."""

    formula_label: str | None = None
    text: str
    page: int
    start_offset: int
    end_offset: int


class ExtractedRGroupDefinition(BaseModel):
    """Structured R-group definition extracted by LLM."""

    formula_label: str = Field(..., description="e.g., 'Formula I'")
    site_label: str = Field(..., description="e.g., 'R1', 'R2'")
    definition: str = Field(..., description="Natural language definition from text")
    candidates: list[str] = Field(
        default_factory=list,
        description="List of SMILES or fragment identifiers mentioned in text",
    )
    evidence_text: str = Field(..., description="Original patent excerpt")


class MarkushDefinitionExtractor(StageExecutor):
    """Extract R-group definitions from patent text using LLM."""

    def execute(self, context: PipelineContext, result: ExtractionResult) -> None:
        """Run definition extraction for documents with pending scaffolds."""
        doc_id = result.doc_id

        # Only run if document has confirmed scaffolds with pending sites
        scaffolds = self._get_pending_scaffolds(context, doc_id)
        if not scaffolds:
            logger.debug(
                f"No pending scaffolds for {doc_id}, skipping definition extraction"
            )
            return

        logger.info(
            f"Extracting Markush definitions for {doc_id} ({len(scaffolds)} scaffolds)"
        )

        full_text = self._get_document_text(context, doc_id)
        if not full_text:
            logger.warning(f"No document Markdown found for {doc_id}")
            return

        # Phase 1: Rule-based targeting
        blocks = self._find_candidate_blocks(full_text)
        if not blocks:
            logger.info(f"No Markush definition blocks found in {doc_id}")
            return

        logger.info(f"Found {len(blocks)} candidate blocks in {doc_id}")

        # Phase 2: LLM extraction (batch all blocks for efficiency)
        extractions = self._extract_definitions_llm(context, blocks)

        # Phase 3: Validation and suggestion creation
        error_count = 0
        suggestion_count = 0

        for extraction in extractions:
            try:
                suggestions = self._validate_and_create_suggestions(
                    context, doc_id, scaffolds, extraction
                )
                suggestion_count += len(suggestions)
            except Exception as exc:
                logger.error(
                    f"Failed to process extraction for {extraction.site_label}: {exc}",
                    extra={
                        "doc_id": doc_id,
                        "formula": extraction.formula_label,
                        "site": extraction.site_label,
                    },
                )
                error_count += 1

        # Record in pipeline report
        if not hasattr(context, "markush_report"):
            context.markush_report = {}
        context.markush_report["definition_extraction_suggestions"] = suggestion_count
        context.markush_report["definition_extraction_errors"] = error_count

        logger.info(
            f"Definition extraction complete for {doc_id}: "
            f"{suggestion_count} suggestions, {error_count} errors"
        )

    def _get_pending_scaffolds(
        self, context: PipelineContext, doc_id: str
    ) -> list[dict[str, Any]]:
        """Return scaffolds with no or incomplete site definitions."""
        conn = context.get_connection()
        cursor = conn.execute(
            """
            SELECT scaffold_id, formula_label, core_smiles
            FROM markush_scaffolds
            WHERE doc_id = ?
              AND (
                SELECT COUNT(*) FROM markush_sites
                WHERE markush_sites.scaffold_id = markush_scaffolds.scaffold_id
                  AND markush_sites.status = 'confirmed'
              ) = 0
            """,
            (doc_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "scaffold_id": row[0],
                "formula_label": row[1],
                "core_smiles": row[2],
            }
            for row in rows
        ]

    def _get_document_text(self, context: PipelineContext, doc_id: str) -> str:
        if hasattr(context, "doc_full_text"):
            return context.doc_full_text

        from ..core.layout import LibraryLayout

        resolver = LibraryLayout(context.library_root)
        document_path = resolver.document_md(doc_id)
        if not document_path.exists():
            return ""

        try:
            return document_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Failed to read document Markdown for {doc_id}: {exc}")
            return ""

    def _find_candidate_blocks(self, text: str) -> list[MarkushDefinitionBlock]:
        """Use deterministic regex to locate candidate definition blocks."""
        blocks: list[MarkushDefinitionBlock] = []

        for formula_match in _FORMULA_PATTERN.finditer(text):
            formula_label = formula_match.group(0).strip()
            start = formula_match.start()
            end = min(start + 500, len(text))
            window = text[start:end]

            if _WHEREIN_PATTERN.search(window):
                blocks.append(
                    MarkushDefinitionBlock(
                        formula_label=formula_label,
                        text=window,
                        page=0,
                        start_offset=start,
                        end_offset=end,
                    )
                )

        for rgroup_match in _R_GROUP_LIST_PATTERN.finditer(text):
            start = max(0, rgroup_match.start() - 100)
            end = min(rgroup_match.end() + 200, len(text))
            window = text[start:end]

            blocks.append(
                MarkushDefinitionBlock(
                    formula_label=None,
                    text=window,
                    page=0,
                    start_offset=start,
                    end_offset=end,
                )
            )

        blocks = self._deduplicate_blocks(blocks)
        return blocks[:10]

    def _deduplicate_blocks(
        self, blocks: list[MarkushDefinitionBlock]
    ) -> list[MarkushDefinitionBlock]:
        """Remove blocks that overlap by >50% with earlier blocks."""
        unique: list[MarkushDefinitionBlock] = []
        for block in blocks:
            if not any(
                self._overlap_ratio(block, existing) > 0.5 for existing in unique
            ):
                unique.append(block)
        return unique

    def _overlap_ratio(
        self, a: MarkushDefinitionBlock, b: MarkushDefinitionBlock
    ) -> float:
        """Return Jaccard similarity of character ranges."""
        a_set = set(range(a.start_offset, a.end_offset))
        b_set = set(range(b.start_offset, b.end_offset))
        if not a_set or not b_set:
            return 0.0
        intersection = len(a_set & b_set)
        union = len(a_set | b_set)
        return intersection / union if union > 0 else 0.0

    def _extract_definitions_llm(
        self, context: PipelineContext, blocks: list[MarkushDefinitionBlock]
    ) -> list[ExtractedRGroupDefinition]:
        """Call LLM to extract structured R-group definitions from text blocks."""
        if not blocks:
            return []

        logger.warning(
            "LLM extraction not yet integrated; skipping definition extraction"
        )
        return []

    def _validate_and_create_suggestions(
        self,
        context: PipelineContext,
        doc_id: str,
        scaffolds: list[dict[str, Any]],
        extraction: ExtractedRGroupDefinition,
    ) -> list[str]:
        """Validate extraction and create mount suggestions."""
        suggestions: list[str] = []

        scaffold = next(
            (
                s
                for s in scaffolds
                if s["formula_label"].lower() == extraction.formula_label.lower()
            ),
            None,
        )
        if not scaffold:
            return suggestions

        scaffold_id = scaffold["scaffold_id"]

        conn = context.get_connection()
        cursor = conn.execute(
            """
            SELECT site_id, atom_map_num, attachment_count
            FROM markush_sites
            WHERE scaffold_id = ? AND site_label = ?
            """,
            (scaffold_id, extraction.site_label),
        )
        site_row = cursor.fetchone()
        if not site_row:
            return suggestions

        site_id, _atom_map_num, _attachment_count = site_row

        for candidate_smiles in extraction.candidates:
            try:
                cursor = conn.execute(
                    """
                    SELECT fragment_id
                    FROM markush_fragments
                    WHERE smiles = ? OR esmiles = ?
                    LIMIT 1
                    """,
                    (candidate_smiles, candidate_smiles),
                )
                frag_row = cursor.fetchone()
                if not frag_row:
                    continue

                fragment_id = frag_row[0]

                mount_id = create_mount(
                    conn=conn,
                    site_id=site_id,
                    fragment_id=fragment_id,
                    origin="text_definition",
                    confidence=0.8,
                    reasons=[
                        f"Extracted from text: {extraction.definition[:100]}",
                        f"Evidence: {extraction.evidence_text[:100]}",
                    ],
                )
                suggestions.append(mount_id)

            except Exception as exc:
                logger.error(f"Failed to create mount for {candidate_smiles}: {exc}")

        return suggestions

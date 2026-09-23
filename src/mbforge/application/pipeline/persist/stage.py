from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.application.pipeline.persist.document_publish import (
    PERSIST_COMPENSATION_FAILED,
    compensate_molecule_persistence,
    persist_document,
)
from mbforge.application.pipeline.run.context import PipelineContext
from mbforge.application.pipeline.stage import PipelineErrorCode, StageResult
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.persist.stage")


def _mapping_markdown_path(ctx: PipelineContext) -> Path | None:
    """Return the authoritative Markdown source for molecule/activity links.

    The final document contains the OCR page markers and ESMILES identities
    used for authoritative text links.
    """
    markdown_path = ctx.document_md_path
    if isinstance(markdown_path, Path) and markdown_path.exists():
        return markdown_path
    return None


class PersistStage:
    name = "persist"

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Persist all data to database + filesystem.

        Reads:
            ctx.candidates: list[Molecule]
            ctx.activity_records: list[ActivityRecord]
            ctx.document_md_path: Path
            ctx.document_evidence: list[SourceEvidence]
            ctx.molecule_stats: dict

        Writes:
            Database: source_evidence, molecules, evidence, text_molecule_links
            Filesystem: storage/{doc_id}/pages/, report.json

        Consistency rule: database writes are committed before filesystem
        artifacts are exposed. If the filesystem write fails, the molecule rows
        written for this document are compensated (deleted) so the DB does not
        reference a document that was not fully persisted.
        """
        from mbforge.application.pipeline.artifacts.hydration import (
            hydrate_context_from_artifacts,
        )

        # Hydrate missing state from stage artifacts before validating —
        # each stage persists readable JSON so persist never depends on a
        # live in-process context from a previous invocation.
        hydrate_context_from_artifacts(ctx)
        if ctx.extracted is None:
            logger.error(
                "Persist stage run without extracted document for %s",
                ctx.doc_id,
            )
            return StageResult(
                stage="persist",
                status="error",
                message="Missing required context: extracted",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )
        if ctx.document_md_path and not ctx.document_md_path.exists():
            return StageResult(
                stage="persist",
                status="error",
                message="Document Markdown is missing; cannot persist document",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )
        if not ctx.document_md_path:
            logger.warning(
                "Persisting %s without a document Markdown artifact", ctx.doc_id
            )

        # The join indexes source evidence before downstream stages run.
        # Verify that SQL-backed evidence is still complete, then persist the
        # secondary molecule/activity/link objects.
        try:
            ctx.source_evidence_count = self._persist_source_evidence(ctx)
            self._persist_molecules_and_links(ctx)
        except Exception as e:
            logger.exception("Database persistence failed for %s: %s", ctx.doc_id, e)
            return StageResult(
                stage="persist",
                status="error",
                message=f"Database persistence failed: {e}",
                error_code=PipelineErrorCode.PERSIST_MOLECULES_FAILED,
                recoverable=False,
                context={"exception_type": type(e).__name__, "detail": str(e)},
            )

        # Persist document to filesystem.
        try:
            self._persist_document(ctx)
        except Exception as e:
            logger.exception("Document persistence failed for %s: %s", ctx.doc_id, e)
            # Compensate the molecule rows already committed for this document so
            # we do not leave DB records for a failed document persist. The
            # original filesystem error stays the primary failure; a
            # compensation error is attached as structured context.
            context: dict[str, Any] = {
                "exception_type": type(e).__name__,
                "detail": str(e),
            }
            try:
                self._compensate_molecule_persistence(ctx)
            except Exception as comp_exc:
                logger.error(
                    "Compensation failed for %s: reason=%s error=%s",
                    ctx.doc_id,
                    PERSIST_COMPENSATION_FAILED,
                    comp_exc,
                )
                context["compensation_failed"] = True
                context["compensation_exception_type"] = type(comp_exc).__name__
                context["compensation_detail"] = str(comp_exc)
            return StageResult(
                stage="persist",
                status="error",
                message=f"Document persistence failed: {e}",
                error_code=PipelineErrorCode.PERSIST_DOCUMENT_FAILED,
                recoverable=False,
                context=context,
            )

        molecule_count = ctx.molecule_stats.get("molecule_count", 0)
        activity_count = ctx.activity_count_written
        return StageResult(
            stage="persist",
            status="success",
            message=f"Persisted {molecule_count} molecules + {activity_count} activities + document",
            context={
                "molecule_count": molecule_count,
                "activity_count": activity_count,
                "source_evidence_count": ctx.source_evidence_count,
                "page_count": ctx.extracted.page_count,
            },
        )

    def _persist_molecules_and_links(self, ctx: PipelineContext) -> None:
        """Persist complete molecules and Markush candidates in one transaction."""
        if not ctx.candidates and not ctx.activity_records:
            logger.info("No molecules to persist for %s", ctx.doc_id)
            return

        from mbforge.application.pipeline.detection.structure_role import (
            classify_structure_role,
        )
        from mbforge.application.pipeline.persist.activities import persist_activities
        from mbforge.application.pipeline.persist.markush import (
            delete_markush_for_doc,
            persist_markush_fragments,
            persist_markush_scaffolds,
        )
        from mbforge.application.pipeline.persist.molecules import (
            persist_molecule_candidates,
        )
        from mbforge.application.pipeline.persist.text_links import (
            enrich_molecule_contexts_from_markdown,
        )
        from mbforge.application.ports import get_database, get_repositories

        mapping_md_path = _mapping_markdown_path(ctx)
        if mapping_md_path:
            enriched_contexts = enrich_molecule_contexts_from_markdown(
                str(mapping_md_path), ctx.candidates
            )
            if enriched_contexts:
                logger.info(
                    "Attached %d authoritative molecule contexts for %s",
                    enriched_contexts,
                    ctx.doc_id,
                )

        for candidate in ctx.candidates:
            classify_structure_role(candidate)

        # Family-core consistency gate: when the document's own Markush
        # scaffolds define a common core, candidates lacking that core
        # (mislabeled reagents/intermediates) are withheld from activity
        # matching so an activity never attaches to the wrong molecule.
        # Their records fall through to the review queue as orphans.
        activity_guard = None
        activity_vetoes: list[Any] = []
        core_smarts: str | None = None
        try:
            from mbforge.application.pipeline.activity.family_gate import (
                derive_family_core,
                make_family_core_guard,
            )

            core_smarts = derive_family_core(ctx.candidates)
            activity_guard = make_family_core_guard(core_smarts)
            if activity_guard is not None:
                logger.info(
                    "Activity family-core guard active for %s: %s",
                    ctx.doc_id,
                    core_smarts,
                )
        except Exception as guard_exc:  # noqa: BLE001 — guard is best-effort
            logger.warning(
                "Family core guard unavailable for %s: %s", ctx.doc_id, guard_exc
            )

        # MS-guided label recovery: a placeholder-named candidate whose
        # exact mass and page agree with a "化合物N … MS m/z X" preparation
        # paragraph gets the label back before activity matching, so the
        # final compound's activity can attach.
        if mapping_md_path and core_smarts:
            try:
                from mbforge.application.pipeline.detection.label_recovery import (
                    recover_labels_from_ms,
                )

                recoveries = recover_labels_from_ms(
                    mapping_md_path.read_text(encoding="utf-8"),
                    ctx.candidates,
                    core_smarts,
                )
                if recoveries:
                    logger.info(
                        "Recovered %d compound labels from MS evidence for %s: %s",
                        len(recoveries),
                        ctx.doc_id,
                        [(recovery.label, recovery.page) for recovery in recoveries],
                    )
            except Exception as recovery_exc:  # noqa: BLE001 — best-effort
                logger.warning(
                    "MS label recovery failed for %s: %s", ctx.doc_id, recovery_exc
                )

        role_counts = {"complete": 0, "scaffold": 0, "fragment": 0}
        for candidate in ctx.candidates:
            if candidate.status != "rejected":
                role = candidate.properties.get("structure_role")
                if role in role_counts:
                    role_counts[role] += 1
        review_candidates = [
            candidate
            for candidate in ctx.candidates
            if candidate.status != "rejected"
            and candidate.properties.get("structure_role") == "review_required"
        ]
        # ``pending_review_count`` is a final role metric, not just the
        # detector's early status.  Context enrichment and the deterministic
        # role classifier run immediately before this point, so expose the
        # count that is actually withheld from the concrete library.
        ctx.molecule_stats["pending_review_count"] = len(review_candidates)
        if review_candidates:
            # Keep the old report shape for documents with no uncertain
            # candidates, but make every withheld candidate observable when
            # the conservative classifier is triggered.
            role_counts["review_required"] = len(review_candidates)
            logger.warning(
                "Withholding %d molecule candidates for manual review in %s: "
                "Markush/context conflict",
                len(review_candidates),
                ctx.doc_id,
            )
        ctx.structure_role_counts = role_counts

        complete_candidates = [
            candidate
            for candidate in ctx.candidates
            if candidate.status != "rejected"
            and candidate.properties.get("structure_role") == "complete"
        ]
        scaffold_candidates = [
            candidate
            for candidate in ctx.candidates
            if candidate.status != "rejected"
            and candidate.properties.get("structure_role") == "scaffold"
        ]
        fragment_candidates = [
            candidate
            for candidate in ctx.candidates
            if candidate.status != "rejected"
            and candidate.properties.get("structure_role") == "fragment"
        ]

        db = get_database(str(ctx.library_root))
        review_repository = get_repositories(ctx.library_root).review

        def _register_links_in_txn(mol_conn: Any) -> None:
            """Register links only for complete candidates in the shared transaction."""
            if not complete_candidates or not mapping_md_path:
                return
            from mbforge.application.pipeline.persist.text_links import (
                register_molecules_from_text,
            )

            register_molecules_from_text(
                str(mapping_md_path),
                complete_candidates,
                ctx.doc_id,
                str(ctx.library_root),
                conn=mol_conn,
            )

        # Run inside cross-database transaction
        with db.transaction() as (_kb_conn, mol_conn):
            if ctx.candidates:
                delete_markush_for_doc(ctx.doc_id, conn=mol_conn)
            if complete_candidates:
                persist_molecule_candidates(
                    str(ctx.library_root),
                    ctx.doc_id,
                    complete_candidates,
                    conn=mol_conn,
                    activity_records=ctx.activity_records,
                    activity_guard=activity_guard,
                    activity_vetoes=activity_vetoes,
                )
            for index, candidate in enumerate(ctx.candidates):
                detection = candidate.detections[0] if candidate.detections else None
                bbox = detection.bbox if detection else None
                page = (
                    detection.page + 1
                    if detection and detection.page is not None
                    else None
                )
                if candidate.status == "rejected":
                    review_repository.insert_review_item(
                        mol_conn,
                        item_id=f"{ctx.doc_id}:unparsable_smiles:{index}",
                        kind="unparsable_smiles",
                        doc_id=ctx.doc_id,
                        page=page,
                        bbox=bbox,
                        crop_relpath=detection.image_path if detection else None,
                        smiles=candidate.esmiles,
                        name=candidate.name,
                        reasons=[candidate.reject_reason or "unparsable_smiles"],
                        payload={"reject_reason": candidate.reject_reason},
                    )
                    continue
                if detection is None or (
                    getattr(detection, "source", "image") == "image"
                    and not detection.image_path
                ):
                    review_repository.insert_review_item(
                        mol_conn,
                        item_id=f"{ctx.doc_id}:missing_evidence:{index}",
                        kind="missing_evidence",
                        doc_id=ctx.doc_id,
                        page=page,
                        bbox=bbox,
                        smiles=candidate.canonical_smiles,
                        name=candidate.name,
                        confidence=detection.confidence if detection else None,
                        reasons=["missing_crop"],
                        payload={"mol_id": candidate.canonical_smiles},
                    )
                elif (
                    candidate.properties.get("structure_role") == "complete"
                    and detection.confidence < 0.5
                ):
                    mol_id = candidate.canonical_smiles
                    review_repository.insert_review_item(
                        mol_conn,
                        item_id=f"{ctx.doc_id}:low_conf_molecule:{mol_id}",
                        kind="low_conf_molecule",
                        doc_id=ctx.doc_id,
                        page=page,
                        bbox=bbox,
                        crop_relpath=detection.image_path,
                        smiles=mol_id,
                        name=candidate.name,
                        confidence=detection.confidence,
                        reasons=["below_confidence_threshold"],
                        payload={"mol_id": mol_id},
                    )
                ocr_labels = candidate.properties.get("ocr_labels")
                if isinstance(ocr_labels, list) and len(ocr_labels) > 1:
                    # Multiple OCR identifier candidates on one molecule:
                    # surface for human disambiguation; confirm adopts the
                    # reviewer-chosen label as the molecule name.
                    review_repository.insert_review_item(
                        mol_conn,
                        item_id=f"{ctx.doc_id}:ambiguous_coref:{index}",
                        kind="ambiguous_coref",
                        doc_id=ctx.doc_id,
                        page=page,
                        bbox=bbox,
                        crop_relpath=detection.image_path if detection else None,
                        smiles=candidate.canonical_smiles,
                        name=candidate.name,
                        confidence=detection.confidence if detection else None,
                        reasons=["multiple_coref_candidates"],
                        payload={
                            "mol_id": candidate.canonical_smiles,
                            "ocr_labels": ocr_labels,
                            "coref_primary": candidate.properties.get(
                                "ocr_labels_primary"
                            ),
                        },
                    )
            persist_markush_scaffolds(ctx.doc_id, scaffold_candidates, conn=mol_conn)
            persist_markush_fragments(ctx.doc_id, fragment_candidates, conn=mol_conn)
            # Review queue: review_required candidates go into the
            # persistent ``markush_review_candidates`` table so the UI
            # can later confirm/reject them. Re-imports supersede old
            # rows but preserve human decisions for unchanged content.
            review_repository.persist_review_candidates(
                ctx.doc_id,
                [
                    c
                    for c in ctx.candidates
                    if c.status != "rejected"
                    and c.properties.get("structure_role") == "review_required"
                ],
                conn=mol_conn,
            )
            # Structured activity persistence — same transaction, same
            # candidate set so row-alignment matches evidence. Capture the
            # actual written count (not the input count) so the report and
            # StageResult reflect the DB, not the LLM extractor's output.
            activity_written = 0
            if ctx.activity_records:
                activity_written = persist_activities(
                    str(ctx.library_root),
                    ctx.doc_id,
                    ctx.activity_records,
                    candidates=complete_candidates,
                    conn=mol_conn,
                    activity_guard=activity_guard,
                )
            ctx.activity_count_written = activity_written
            _register_links_in_txn(mol_conn)

        if activity_vetoes:
            logger.warning(
                "Withheld activity from %d candidates lacking the family core in %s: %s",
                len(activity_vetoes),
                ctx.doc_id,
                [(v.name, v.reason) for v in activity_vetoes],
            )

        logger.info(
            "Persisted structure roles %s for %s",
            role_counts,
            ctx.doc_id,
        )

    def _persist_source_evidence(self, ctx: PipelineContext) -> int:
        """Return the count of already-indexed joined source evidence."""
        from mbforge.application.pipeline.artifacts.evidence_join import (
            load_document_evidence,
        )

        evidence = load_document_evidence(ctx.library_root, ctx.doc_id)
        if not evidence:
            raise RuntimeError("Missing joined source evidence artifact")
        ctx.document_evidence = evidence
        return len(evidence)

    def _persist_document(self, ctx: PipelineContext) -> None:
        """Delegate to :mod:`mbforge.application.pipeline.persist.document_publish`."""
        persist_document(ctx)

    def _compensate_molecule_persistence(self, ctx: PipelineContext) -> None:
        """Delegate to :mod:`mbforge.application.pipeline.persist.document_publish`."""
        compensate_molecule_persistence(ctx)

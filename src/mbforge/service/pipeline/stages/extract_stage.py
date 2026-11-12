"""Stage 1: Extract page layout, text and molecules with the local producers.

Two producers read the PDF from their own handles and run concurrently:

- the **layout producer** renders every page once at the layout zoom and runs
  Hiro-Layout plus layout-guided text and table recognition
  (:mod:`mbforge.service.pipeline.layout.parse`);
- the **molecule pass** renders every page at ``moldet.detection_dpi``, runs
  MolDet and reads each box into SMILES / E-SMILES with MolParser, archiving
  its crops under the staging directory
  (:mod:`mbforge.service.pipeline.detection.extraction`).

Both feed the single piece of work this stage owns: minting the canonical
``SourceEvidence`` rows and persisting them.  There is no intermediate branch
artifact — SQL is the only evidence store.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.cancellation import (
    TaskCancelledError,
    default_registry,
    make_cancel_check,
)
from mbforge.service.pipeline.detection.normalization import (
    resolve_repeated_print_labels,
)
from mbforge.service.pipeline.run.context import PipelineContext
from mbforge.service.pipeline.stage import PipelineErrorCode, StageResult, register

logger = get_logger("mbforge.service.pipeline.stages.extract")


class StructureRecognitionError(RuntimeError):
    """Recognized drawings carry no structure at all for this document."""


def _recognition_failure(results: list[Any], candidates: list[Any]) -> str | None:
    """Return why no drawing carries a structure, or ``None`` when some do.

    A recognizer that never loaded returns an empty SMILES for every crop.
    Persisting that mints molecule evidence rows with no structure, and the
    document then looks extracted while every reading is unownable — measured
    on CN120118069A, where a ``from_pretrained`` crash (broken stderr, see
    ``molparser._flushable_stderr``) cost the model and the run still reported
    success with 0 activity-backed molecules. Recognition failure is a stage
    failure; an empty result is not a result.
    """
    if not results:
        return None
    if any(
        str(getattr(item, "canonical_smiles", "") or "").strip() for item in candidates
    ):
        return None
    return (
        f"{len(results)} drawings were detected but no structure was recognized; "
        "the molecule recognizer failed to load or returned nothing"
    )


def _name_drawings_from_page_text(
    results: list[Any],
    pages: list[Any],
    page_heights: dict[int, float],
) -> int:
    """Give every drawing the number the page prints beside it.

    The molecule pass reads a compound number off the crop around a drawing, and
    a number printed in the margin never reaches that crop: a US application
    prints its compound list as ``[drawing][A-5]``. The page's own text has the
    number, with its position, so the drawing is named from there.

    Only drawings the crop pass left unnamed are considered, and only a number
    that names no drawing already is used.
    """
    from mbforge.domain.patent import designation_key
    from mbforge.service.pipeline.detection.text_label_assignment import (
        assign_text_labels,
        page_designations,
        to_top_down,
    )

    by_page: dict[int, list[Any]] = {}
    for result in results:
        if result.page_idx is None or result.bbox_pdf is None:
            continue
        by_page.setdefault(result.page_idx + 1, []).append(result)

    named = 0
    for page in pages:
        page_results = by_page.get(page.page_num, [])
        height = page_heights.get(page.page_num)
        if not page_results or not height:
            continue
        free = [result for result in page_results if not str(result.name).strip()]
        if not free:
            continue
        taken = {
            designation_key(str(result.name))
            for result in page_results
            if str(result.name).strip()
        }
        designations = [
            designation
            for designation in page_designations(page.regions, height)
            if designation_key(designation.text) not in taken
        ]
        if not designations:
            continue
        structures = [
            (str(index), to_top_down(result.bbox_pdf, height))
            for index, result in enumerate(free)
        ]
        assignment = assign_text_labels(structures, designations)
        for token, structure_id in assignment.assignments.items():
            key = designation_key(token)
            if not key or key in taken:
                continue
            taken.add(key)
            result = free[int(structure_id)]
            result.name = key
            result.properties["ocr_labels"] = [key]
            result.properties["ocr_labels_primary"] = key
            result.properties["label_source"] = "page_text"
            named += 1
    return named


def _detect_molecules(ctx: PipelineContext) -> dict[str, Any]:
    """Run the molecule pass and return its raw results plus stats.

    Never fatal: a failure records the reason in the returned stats and leaves
    the document with page text and layout only, which is strictly better than
    publishing nothing at all. Crops are archived into the staging directory so
    the artifact can reference them by library-relative path.
    """
    from mbforge.service.pipeline.detection.extraction import (
        extract_molecules_from_pdf,
    )

    try:
        image_results = extract_molecules_from_pdf(
            str(ctx.pdf_path),
            str(ctx.library_root),
            ctx.doc_id,
            cancel_check=make_cancel_check(default_registry, ctx.task_id),
            staging_dir=str(ctx.staging_dir) if ctx.staging_dir is not None else None,
        )
    except TaskCancelledError:
        raise
    except Exception as exc:
        logger.warning("Molecule extraction failed for %s: %s", ctx.doc_id, exc)
        return {
            "molecule_count": 0,
            "rejected_count": 0,
            "skipped": True,
            "reason": f"extraction_failed: {exc}",
            "error": f"extraction_failed: {exc}",
            "results": [],
        }

    if not image_results:
        return {
            "molecule_count": 0,
            "rejected_count": 0,
            "skipped": True,
            "reason": "no molecule images detected",
            "results": [],
        }

    return {
        "molecule_count": len(image_results),
        "rejected_count": 0,
        "total_candidates": len(image_results),
        "results": image_results,
    }


@register
class ExtractStage:
    name = "extract"
    """Stage 1: Extract page layout, text and molecules."""

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Extract layout regions, text and molecules from the PDF.

        Writes:
            ctx.extracted: ExtractedDocument
            ctx.molecule_stats: dict
            ctx.source_evidence_count: number of persisted evidence rows
            ctx.candidates: list[Molecule] — always empty; candidates are
                rebuilt from SQL at Markdown/Patent.
        """
        if not ctx.run_id:
            return StageResult(
                stage="extract",
                status="error",
                message="Missing extract branch context",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )
        try:
            from mbforge.foundation.config import load_global_config
            from mbforge.service.pipeline.artifacts.evidence_join import (
                _candidates_from_evidence,
                mint_evidence,
                page_frames_from_pdf,
            )
            from mbforge.service.pipeline.detection.structure_role import (
                classify_structure_role,
            )
            from mbforge.service.pipeline.extract.anchors import (
                build_label_anchors,
                build_page_geometry,
            )
            from mbforge.service.pipeline.extract.text import extract_layout_text
            from mbforge.service.ports import get_repositories

            layout_config = load_global_config().layout

            with ThreadPoolExecutor(max_workers=2) as pool:
                layout_future = pool.submit(
                    extract_layout_text,
                    str(ctx.pdf_path),
                    doc_id=ctx.doc_id,
                    layout_config=layout_config.model_dump(),
                    cancel_check=make_cancel_check(default_registry, ctx.task_id),
                )
                molecules_future = pool.submit(_detect_molecules, ctx)
                # The layout producer owns the document: without page text there
                # is no evidence at all, so its failure is fatal.
                ctx.extracted = layout_future.result()
                molecule_stats = molecules_future.result()

            ctx.molecule_stats = molecule_stats
            ctx.candidates = []

            frames = page_frames_from_pdf(ctx.pdf_path)
            repeated = resolve_repeated_print_labels(
                list(molecule_stats.get("results", []))
            )
            if repeated:
                logger.info(
                    "Named %d drawings from a number printed on the same "
                    "compound twice",
                    repeated,
                )
            named_from_text = _name_drawings_from_page_text(
                list(molecule_stats.get("results", [])),
                list(ctx.extracted.pages),
                {frame.page: frame.height for frame in frames},
            )
            if named_from_text:
                logger.info(
                    "Named %d drawings from the page's own text", named_from_text
                )

            evidence = mint_evidence(
                ctx.extracted,
                frames,
                list(molecule_stats.get("results", [])),
                doc_id=ctx.doc_id,
                library_root=ctx.library_root,
                staging_dir=ctx.staging_dir,
            )
            candidates = _candidates_from_evidence(
                list(molecule_stats.get("results", [])), evidence
            )
            for candidate in candidates:
                classify_structure_role(candidate)

            failure = _recognition_failure(
                list(molecule_stats.get("results", [])), candidates
            )
            if failure is not None:
                raise StructureRecognitionError(failure)

            repositories = get_repositories(ctx.library_root)
            ctx.source_evidence_count = repositories.evidence.persist(evidence)
            # ADR 0001: persist the printed-designation anchor index beside the
            # evidence it cites, so association becomes a lookup instead of an
            # in-memory rebuild. Derived from the same evidence rows, so each
            # anchor already carries its evidence_id and geometry.
            anchors = build_label_anchors(evidence, doc_id=ctx.doc_id)
            geometry = build_page_geometry(ctx.doc_id, frames)
            anchor_count = repositories.anchors.persist(ctx.doc_id, anchors, geometry)
            # Concrete structures have to reach ``molecules`` here: nothing later
            # does it. The Patent stage only re-persists candidates it can prove
            # an activity belongs to, so a molecule without a reading (or whose
            # reading is still unbound) used to exist on disk as a crop and in
            # no table at all — the library reported 0 molecules for documents
            # that recognized thousands.
            from mbforge.service.pipeline.persist.molecules import (
                persist_molecule_candidates,
            )

            persist_molecule_candidates(
                ctx.library_root,
                ctx.doc_id,
                [
                    c
                    for c in candidates
                    if c.properties.get("structure_role") == "complete"
                ],
            )

            molecule_count = molecule_stats.get("molecule_count", 0)
            logger.info(
                "Extracted %d pages (%d chars, %d molecules, %d evidence rows, "
                "%d anchors) from %s",
                ctx.extracted.page_count,
                len(ctx.extracted.raw_text),
                molecule_count,
                ctx.source_evidence_count,
                anchor_count,
                ctx.doc_id,
            )

            warning = ""
            if molecule_stats.get("skipped"):
                warning = (
                    "molecule extraction skipped: "
                    f"{molecule_stats.get('reason', 'unknown reason')}"
                )

            return StageResult(
                stage="extract",
                status="success",
                message=(
                    f"Extracted {ctx.extracted.page_count} pages "
                    f"({len(ctx.extracted.raw_text)} chars, "
                    f"{molecule_count} molecules, "
                    f"{ctx.source_evidence_count} evidence rows)"
                ),
                warnings=[warning] if warning else [],
                context={
                    "page_count": ctx.extracted.page_count,
                    "parser": ctx.extracted.parser,
                    "title": ctx.extracted.title,
                    "ocr": ctx.extracted.ocr_stats,
                    "molecule_count": molecule_count,
                    "rejected_count": molecule_stats.get("rejected_count", 0),
                    "skipped": molecule_stats.get("skipped", False),
                    "source_evidence_count": ctx.source_evidence_count,
                    "label_anchor_count": anchor_count,
                    "tool_stats": molecule_stats.get("tool_stats", {}),
                },
            )

        except TaskCancelledError:
            # Cooperative cancellation aborts the pipeline with its own
            # error code; never report it as a PDF parse failure.
            raise
        except Exception as e:
            logger.error(
                "Text extraction failed for %s: %s", ctx.doc_id, e, exc_info=True
            )
            from mbforge.service.pipeline.layout.parse import LayoutUnavailableError

            if isinstance(e, StructureRecognitionError):
                error_code = PipelineErrorCode.MOLECULE_RECOGNITION_UNAVAILABLE
                message_prefix = "Molecule recognition unavailable"
            elif isinstance(e, LayoutUnavailableError):
                error_code = PipelineErrorCode.LAYOUT_UNAVAILABLE
                message_prefix = "Layout detection unavailable"
            else:
                error_code = PipelineErrorCode.PDF_PARSE_ERROR
                message_prefix = "Text extraction failed"
            return StageResult(
                stage="extract",
                status="error",
                message=f"{message_prefix}: {e}",
                error_code=error_code,
                recoverable=False,
                context={"exception_type": type(e).__name__, "detail": str(e)},
            )


__all__ = ["ExtractStage"]

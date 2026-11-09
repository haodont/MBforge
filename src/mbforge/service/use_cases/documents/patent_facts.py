"""Patent facts: the single publication path and the read side.

Publication commits the document's facts and its permitted derived rows in one
transaction and then refreshes ``storage/{doc_id}/patent_facts.json``, which is
a rebuildable *projection* of the committed snapshot. Reads prefer the snapshot,
so a stale file never wins over committed facts, and bring the file back up to
date when it is missing or behind.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from mbforge.contracts.measurement import DESIGNATION_UNBOUND_KIND
from mbforge.contracts.patent import PATENT_FACT_REVIEW_KIND, PatentConflict
from mbforge.foundation.ids import stable_id
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.artifacts.json_io import (
    read_json_object,
    write_json_atomic,
)
from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.service.pipeline.patent.decisions import apply_decisions
from mbforge.service.ports import get_repositories

logger = get_logger("mbforge.service.use_cases.documents.patent_facts")


# ── publication ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class PublicationResult:
    """What one publication committed, and whether its projection landed."""

    revision: int
    projection_path: Path
    projection_ok: bool
    molecule_count: int
    review_items: int = 0
    projection_error: str | None = None


def publish_document_facts(
    library_root: str | Path,
    *,
    doc_id: str,
    artifact: PatentFactsArtifact,
    evidence_signature: str,
    candidates: Sequence[Any] = (),
    decisions: dict[str, Any] | None = None,
    forget_decisions: Sequence[str] = (),
    expected_revision: int | None = None,
) -> PublicationResult:
    """Commit *artifact* and its derived rows, then refresh the file projection.

    The commit is a single transaction (snapshot + derived rows). Pending facts
    are queued for review by item id, so a re-run upserts the same items instead
    of duplicating them. A failed *file* write is reported as a projection that
    needs repair — the committed facts are already authoritative and are never
    rolled back for it.
    """
    root = Path(library_root)
    artifact = artifact.model_copy(update={"projection_status": None})
    stored = _live_decisions(root, doc_id, decisions=decisions, forget=forget_decisions)
    artifact, stale = _with_decisions(
        artifact, stored=stored, doc_id=doc_id, evidence_signature=evidence_signature
    )
    for slot_id in stale:
        stored.pop(slot_id, None)
    eligible, activity_updates = _derived_rows(artifact, candidates)
    readings, attributions = _reading_rows(artifact, candidates)
    revision = get_repositories(root).patent_analysis.commit(
        doc_id=doc_id,
        evidence_signature=evidence_signature,
        analysis_status=artifact.analysis_status,
        extraction_mode=artifact.extraction_mode,
        payload=artifact.model_dump(exclude={"revision", "projection_status"}),
        candidates=eligible,
        activity_updates=activity_updates,
        measurements=readings,
        attributions=attributions,
        decisions=stored,
        forget_decisions=stale,
        expected_revision=expected_revision,
    )
    review_items = _queue_review_items(
        root, doc_id, artifact, revision, candidates=eligible
    )
    projection = LibraryLayout(root).patent_facts_json(doc_id)
    try:
        write_json_atomic(
            projection,
            artifact.model_copy(update={"revision": revision}).model_dump(
                exclude={"projection_status"}
            ),
        )
    except OSError as exc:
        logger.error(
            "Patent facts committed (revision %d) but the file projection failed "
            "for %s: %s",
            revision,
            doc_id,
            exc,
        )
        return PublicationResult(
            revision=revision,
            projection_path=projection,
            projection_ok=False,
            molecule_count=len(eligible),
            review_items=review_items,
            projection_error=str(exc),
        )
    return PublicationResult(
        revision=revision,
        projection_path=projection,
        projection_ok=True,
        molecule_count=len(eligible),
        review_items=review_items,
    )


def _live_decisions(
    library_root: Path,
    doc_id: str,
    *,
    decisions: dict[str, Any] | None,
    forget: Sequence[str],
) -> dict[str, Any]:
    """The stored decisions plus this publication's update, minus withdrawn slots."""
    state = get_repositories(library_root).patent_analysis.load(doc_id)
    stored = dict((state or {}).get("decisions") or {})
    if decisions:
        stored.update(decisions)
    for slot_id in forget:
        stored.pop(slot_id, None)
    return stored


def _with_decisions(
    artifact: PatentFactsArtifact,
    *,
    stored: Mapping[str, Any],
    doc_id: str,
    evidence_signature: str,
) -> tuple[PatentFactsArtifact, list[str]]:
    """Fold the still-valid decisions into the pending facts.

    Returns the artifact to publish and the slots whose decision no longer
    matches the facts (a re-extract invalidates them; they must be reviewed
    again rather than applied to different readings).
    """
    if not artifact.conflicts and not stored:
        return artifact, []
    conflicts = [PatentConflict.model_validate(raw) for raw in artifact.conflicts]
    application = apply_decisions(
        doc_id=doc_id,
        measurements=artifact.measurements,
        candidates=artifact.review_candidates,
        conflicts=conflicts,
        decisions=stored,
        evidence_signature=evidence_signature,
    )
    resolved = artifact.model_copy(
        update={
            "measurements": application.measurements,
            "review_candidates": application.candidates,
            "conflicts": [item.model_dump() for item in application.conflicts],
        }
    )
    return resolved, application.stale


def _queue_review_items(
    library_root: Path,
    doc_id: str,
    artifact: PatentFactsArtifact,
    revision: int,
    *,
    candidates: Sequence[Any] = (),
) -> int:
    """Queue one review item per pending fact (idempotent per item id).

    A publication must never re-open a decision a human already made: the item
    id is derived from the candidate set itself (slot plus the signatures of
    both readings), so a changed candidate set is a new item, and an unchanged
    one keeps whatever status it reached. Nothing here writes ``status``.
    """
    review = get_repositories(library_root).review
    queued = 0
    for candidate in artifact.review_candidates:
        item_id = str(candidate.get("review_item_id") or "")
        if not item_id:
            continue
        review.insert_review_item(
            item_id=item_id,
            kind=PATENT_FACT_REVIEW_KIND,
            doc_id=doc_id,
            page=candidate.get("page"),
            reasons=[str(candidate.get("reason") or "")],
            context_text=_candidate_context(candidate),
            payload={
                "doc_id": doc_id,
                "slot_id": candidate.get("slot_id"),
                "revision": revision,
                "deterministic": candidate.get("deterministic"),
                "llm": candidate.get("llm"),
                "conflict": candidate.get("conflict"),
            },
        )
        queued += 1
    queued += _queue_mass_mismatches(review, doc_id, artifact)
    queued += _queue_unbound_readings(
        review, doc_id, artifact, candidates, library_root=library_root
    )
    return queued


#: A printed MS mass that disagrees with the structure's own mass.
MASS_MISMATCH_CODE = "smiles_mass_mismatch"


def _queue_mass_mismatches(
    review: Any, doc_id: str, artifact: PatentFactsArtifact
) -> int:
    """Queue one structure correction per printed mass that disagrees.

    The rule detects and evidences the disagreement; the replacement structure is a
    human's, applied only on confirm (``review_queue.decide``). The item id is
    derived from the mismatch itself, so a re-run upserts the same item and a
    changed detection is a new one.
    """
    queued = 0
    for issue in artifact.issues:
        if str(issue.get("code") or "") != MASS_MISMATCH_CODE:
            continue
        mol_id = str(issue.get("mol_id") or "")
        if not mol_id:
            continue
        item_id = stable_id(
            "smiles-mismatch",
            doc_id,
            mol_id,
            str(issue.get("printed_mz") or ""),
            str(issue.get("calculated_mass") or ""),
        )
        review.insert_review_item(
            item_id=item_id,
            kind="smiles_correction",
            doc_id=doc_id,
            page=issue.get("page"),
            smiles=str(issue.get("structure_smiles") or ""),
            reasons=["printed_ms_mass_disagrees"],
            context_text=str(issue.get("raw_text") or "")[:500],
            payload={
                "doc_id": doc_id,
                "mol_id": mol_id,
                "printed_mz": issue.get("printed_mz"),
                "calculated_mass": issue.get("calculated_mass"),
                "delta": issue.get("delta"),
                "adduct": issue.get("adduct"),
                "evidence_ids": list(issue.get("evidence_ids") or [])[:10],
                "raw_text": issue.get("raw_text"),
            },
        )
        queued += 1
    return queued


def _designation_scope(artifact: PatentFactsArtifact) -> dict[str, set[int]]:
    """Page ranges of the sections whose title declares each designation.

    A table reading cites ``化合物11``; the compound is drawn in the example
    section titled ``实施例11：目标化合物11制备``. The section title is the
    document telling us where to look, without guessing a page.
    """
    import re

    scope: dict[str, set[int]] = {}
    for section in artifact.sections:
        if hasattr(section, "model_dump"):
            section = section.model_dump()
        if not isinstance(section, dict):
            continue
        start = section.get("page_start")
        end = section.get("page_end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        title = str(section.get("title") or "")
        for match in re.finditer(
            r"化合物\s*([0-9]{1,4}[A-Za-z]?(?:-[A-Za-z])?)", title
        ):
            scope.setdefault(match.group(1), set()).update(range(start, end + 1))
    return scope


def _queue_unbound_readings(
    review: Any,
    doc_id: str,
    artifact: PatentFactsArtifact,
    candidates: Sequence[Any],
    *,
    library_root: str | Path | None = None,
) -> int:
    """Queue one item per printed reading whose structure could not be bound.

    The candidates are not "the page the table is on": a reading sits in a result
    table while its compound is drawn in the example section that prepares it.
    So the scope is the section that declares the designation (its page range),
    plus the reading page itself. A reading whose section drew nothing is a source
    fact, not a review question, and is not queued.

    Confirming the item with ``choice=<candidate mol_id>`` writes the attribution
    (method=human) — that is the only thing a decision on this kind does.
    """
    if library_root is not None:
        # Every recognized structure, not only the persistable ones: a drawing
        # the pipeline flagged for review is still a candidate a human can pick.
        from mbforge.service.pipeline.artifacts.hydration import load_detections

        try:
            loaded = load_detections(library_root, doc_id)
        except Exception as exc:  # noqa: BLE001 - one bad payload must not block
            # A malformed detection payload is a data defect, not a publication
            # failure: the review items are a convenience over the published facts.
            logger.warning(
                "Could not gather unbound-reading candidates for %s: %s",
                doc_id,
                exc,
            )
            loaded = None
        if loaded:
            candidates = list(loaded[0])
    drawn: list[tuple[set[int], dict[str, str]]] = []
    seen: set[str] = set()
    for candidate in candidates:
        detections = list(getattr(candidate, "detections", []) or [])
        if not detections or detections[0].page is None:
            continue
        smiles = str(getattr(candidate, "canonical_smiles", "") or "")
        if not smiles or smiles in seen:
            continue
        seen.add(smiles)
        raw_page = int(detections[0].page)
        # Page bases differ across producers; accepting both neighbours keeps the
        # scope right without a page-basis assumption that is easy to get wrong.
        pages = {raw_page - 1, raw_page, raw_page + 1}
        drawn.append(
            (
                pages,
                {
                    "mol_id": smiles,
                    "smiles": smiles,
                    "name": str(getattr(candidate, "name", "") or ""),
                },
            )
        )
    sections = {}
    for raw_section in artifact.sections:
        section = (
            raw_section.model_dump()
            if hasattr(raw_section, "model_dump")
            else raw_section
        )
        if isinstance(section, dict) and section.get("section_id"):
            sections[str(section["section_id"])] = section
    entries = {
        str(entry.get("entry_id")): entry
        for entry in artifact.entries
        if isinstance(entry, dict) and entry.get("entry_id")
    }
    declared = _designation_scope(artifact)
    queued = 0
    for measurement in artifact.measurements:
        if not isinstance(measurement, dict):
            continue
        if measurement.get("mol_id"):
            continue
        entry = entries.get(str(measurement.get("compound_entry_id") or ""))
        if entry is not None and entry.get("entity_id"):
            continue
        provenance = measurement.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        designation = str(provenance.get("reference_key") or "")
        measurement_id = str(measurement.get("measurement_id") or "")
        page = measurement.get("page_num")
        if not designation or not measurement_id:
            continue
        scope: set[int] = set()
        if isinstance(page, int):
            scope.update({page - 1, page, page + 1})
        section = None
        if entry is not None:
            section = sections.get(str(entry.get("section_id") or ""))
        if section is not None:
            start = section.get("page_start")
            end = section.get("page_end")
            if isinstance(start, int) and isinstance(end, int):
                scope.update(range(start, end + 1))
        scope |= declared.get(designation, set())
        picked = [item for pages, item in drawn if pages & scope]
        if not picked:
            continue
        review.insert_review_item(
            item_id=stable_id("unbound", doc_id, measurement_id),
            kind=DESIGNATION_UNBOUND_KIND,
            doc_id=doc_id,
            page=page if isinstance(page, int) else None,
            name=designation,
            reasons=["designation_without_structure"],
            context_text=str(measurement.get("raw_text") or "")[:300] or None,
            payload={
                "doc_id": doc_id,
                "measurement_id": measurement_id,
                "designation": designation,
                "metric": measurement.get("metric"),
                "value": measurement.get("value"),
                "page": page,
                "section_id": (entry or {}).get("section_id"),
                "evidence_ids": list(measurement.get("evidence_ids") or [])[:10],
                "candidates": picked[:8],
            },
        )
        queued += 1
    return queued


def _candidate_context(candidate: Mapping[str, Any]) -> str:
    """One-line summary of the readings a reviewer has to compare."""

    def _value_text(fields: Any) -> str:
        if isinstance(fields, Mapping):
            return str(fields.get("value_text") or "")
        if isinstance(fields, list) and fields and isinstance(fields[0], Mapping):
            return str(fields[0].get("value_text") or "")
        return ""

    deterministic = _value_text(candidate.get("deterministic"))
    llm = _value_text(candidate.get("llm"))
    parts = [f"deterministic: {deterministic}"] if deterministic else []
    if llm:
        parts.append(f"llm: {llm}")
    return " | ".join(parts)[:500]


def _reading_rows(
    artifact: PatentFactsArtifact, candidates: Sequence[Any]
) -> tuple[list[Any], list[Any]]:
    """Every printed reading plus the structure links that actually resolved.

    Unlike ``_derived_rows``, this does not filter by structure: a reading the
    document printed is stored whether or not a molecule owns it. That keeps the
    dataset complete and makes the extraction backlog countable instead of
    silently dropping most readings.
    """
    from mbforge.service.pipeline.patent.measurement_records import (
        measurement_attributions,
        measurement_records,
    )

    readings = measurement_records(
        doc_id=artifact.doc_id,
        run_id=artifact.run_id or None,
        measurements=artifact.measurements,
        assay_methods=artifact.assay_methods,
    )
    attributions = measurement_attributions(
        doc_id=artifact.doc_id,
        records=readings,
        measurements=artifact.measurements,
        entries=artifact.entries,
    )
    return readings, attributions


def _derived_rows(
    artifact: PatentFactsArtifact, candidates: Sequence[Any]
) -> tuple[list[Any], list[dict[str, Any]]]:
    """The persistable candidates and their activity updates (valid facts only)."""
    from mbforge.service.pipeline.persist.molecules import (
        filter_persistable_candidates,
    )

    candidates_by_smiles = {
        candidate.canonical_smiles.strip(): candidate
        for candidate in candidates
        if isinstance(getattr(candidate, "canonical_smiles", None), str)
        and candidate.canonical_smiles.strip()
    }
    # A candidate answers to two names: canonical SMILES, which is what gets
    # persisted, and ``mol_id``, which is what a gap payload and the model's link
    # carry. Both resolve here, so a link that named the ``mol_id`` is not lost.
    by_ref: dict[str, Any] = {**candidates_by_smiles}
    for candidate in candidates_by_smiles.values():
        mol_ref = str(getattr(candidate, "mol_id", "") or "").strip()
        if mol_ref:
            by_ref.setdefault(mol_ref, candidate)

    measurements_by_smiles: dict[str, list[dict[str, Any]]] = {}
    for measurement in artifact.measurements:
        if not isinstance(measurement, dict) or not _measurement_has_activity(
            measurement
        ):
            continue
        entry = next(
            (
                item
                for item in artifact.entries
                if item.get("entry_id") == measurement.get("compound_entry_id")
            ),
            None,
        )
        # The designation's structure, however it was resolved: a declared entry
        # carries it, and a reading the model bound to one carries it on itself.
        ref = entry.get("entity_id") if isinstance(entry, dict) else None
        if not (isinstance(ref, str) and ref.strip()):
            ref = measurement.get("mol_id")
        candidate = by_ref.get(ref.strip()) if isinstance(ref, str) else None
        if candidate is None:
            continue
        measurements_by_smiles.setdefault(
            candidate.canonical_smiles.strip(), []
        ).append(measurement)

    eligible = filter_persistable_candidates(
        artifact.doc_id,
        [candidates_by_smiles[smiles] for smiles in measurements_by_smiles],
        warn=False,
    )
    activity_updates: list[dict[str, Any]] = []
    for candidate in eligible:
        measurement = measurements_by_smiles[candidate.canonical_smiles.strip()][0]
        value = measurement.get("value") or {}
        canonical_value = value.get("canonical_value")
        if canonical_value is None:
            canonical_value = value.get("original_value")
        activity_updates.append(
            {
                "mol_id": candidate.canonical_smiles,
                "activity": canonical_value,
                "activity_type": measurement.get("metric") or "activity",
                "units": value.get("canonical_unit")
                or value.get("original_unit")
                or "",
            }
        )
    return eligible, activity_updates


def _measurement_has_activity(measurement: dict[str, Any]) -> bool:
    """Return whether a Patent measurement has a reading and a named owner.

    The owner is the entry the reading cites, or the structure it resolved to
    directly: a reading the model bound to a recognized structure names one too,
    and both are checked against this document's candidates later.
    """
    owner = measurement.get("compound_entry_id") or measurement.get("mol_id")
    if not isinstance(owner, str) or not owner.strip():
        return False
    value = measurement.get("value")
    if not isinstance(value, dict):
        return False
    return any(
        value.get(key) not in (None, "")
        for key in (
            "canonical_value",
            "original_value",
            "qualitative_value",
            "raw_text",
        )
    )


# ── read side ─────────────────────────────────────────────────────────


def load_patent_facts(
    library_root: str | Path, doc_id: str
) -> PatentFactsArtifact | None:
    """Return the document's Patent facts, preferring the committed snapshot.

    A snapshot with a cleared payload means the document has no committed facts
    right now, so the legacy file is not consulted for it either.
    """
    root = Path(library_root)
    state = get_repositories(root).patent_analysis.load(doc_id)
    if state is not None:
        payload = state.get("payload") or {}
        if not payload:
            return None
        payload = {**payload, "revision": int(state.get("revision") or 0)}
        try:
            artifact = PatentFactsArtifact.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 — a broken snapshot reads as absent
            logger.warning(
                "Ignoring malformed committed patent facts for %s: %s", doc_id, exc
            )
            return None
        status = _repair_projection(root, doc_id, artifact)
        return artifact.model_copy(update={"projection_status": status})

    data = read_json_object(
        LibraryLayout(root).patent_facts_json(doc_id), label="patent facts"
    )
    if data is None:
        return None
    try:
        return PatentFactsArtifact.model_validate(data).model_copy(
            update={"projection_status": "legacy"}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ignoring malformed patent facts for %s: %s", doc_id, exc)
        return None


def _repair_projection(
    library_root: Path, doc_id: str, artifact: PatentFactsArtifact
) -> Literal["current", "pending"]:
    """Observe full content and repair a missing, damaged or stale projection."""
    path = LibraryLayout(library_root).patent_facts_json(doc_id)
    payload = artifact.model_dump(exclude={"projection_status"})
    try:
        existing = read_json_object(path, label="patent facts projection")
        if existing == payload:
            return "current"
        write_json_atomic(path, payload)
        logger.info(
            "Repaired the patent facts projection for %s (revision %d)",
            doc_id,
            artifact.revision,
        )
        return "current"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not repair the patent facts projection for %s: %s", doc_id, exc
        )
        return "pending"


__all__ = [
    "PublicationResult",
    "load_patent_facts",
    "publish_document_facts",
]

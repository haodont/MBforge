"""Export every committed reading with its document-local structure and evidence."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from mbforge.domain.patent_analysis import evidence_signature
from mbforge.foundation.errors import ConflictError, NotFoundError, ValidationError
from mbforge.service.pipeline.artifacts.hydration import load_detections
from mbforge.service.pipeline.patent.measurement_records import measurement_records
from mbforge.service.pipeline.persist.molecules import filter_persistable_candidates
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.patent_facts import load_patent_facts

_COLUMNS = (
    "doc_id",
    "file_name",
    "revision",
    "measurement_id",
    "entry_id",
    "designation",
    "mol_id",
    "canonical_smiles",
    "recognized_smiles",
    "current_canonical_smiles",
    "metric",
    "original_value",
    "original_unit",
    "operator_original",
    "canonical_metric",
    "canonical_value",
    "canonical_unit",
    "operator",
    "scale",
    "value_text",
    "measurement_kind",
    "qualitative_raw",
    "qualitative_rank",
    "qualitative_scheme",
    "qualitative_label",
    "target",
    "species",
    "assay_method_id",
    "assay_type",
    "conditions",
    "review_status",
    "structure_review_status",
    "missing_fields",
    "reasons",
    "page_num",
    "table_idx",
    "row_idx",
    "col_idx",
    "reading_evidence_ids",
    "structure_evidence_ids",
    "entry_evidence_ids",
    "assay_evidence_ids",
)


def _csv(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        cells: dict[str, Any] = {}
        for key in _COLUMNS:
            value = row.get(key)
            if isinstance(value, dict | list):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            # Keep spreadsheet programs from executing source text as formulas.
            if isinstance(value, str) and value.lstrip().startswith(
                ("=", "+", "-", "@")
            ):
                value = "'" + value
            cells[key] = value
        writer.writerow(cells)
    return stream.getvalue().encode("utf-8-sig")


def export_structure_activity(
    library_root: str | Path, doc_ids: Sequence[str]
) -> bytes:
    """Build a ZIP from fresh SQL snapshots, without query limits or scalar collapse.

    Matched rows still require scientific review. Missing/conflicting structures
    and incomplete citations go to unresolved.csv, retaining the original reading.
    dataset.json includes exact snapshots and SQL evidence for independent replay.
    """
    if not doc_ids:
        raise ValidationError("Select at least one document to export.")
    root = Path(library_root)
    repos = get_repositories(root)
    paired: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    stamps: dict[str, tuple[int, str]] = {}
    for doc_id in dict.fromkeys(doc_ids):
        document = repos.documents.get(doc_id)
        if document is None:
            raise NotFoundError(f"Document not found: {doc_id}")
        facts = load_patent_facts(root, doc_id)
        state = repos.patent_analysis.load(doc_id)
        evidence = repos.evidence.list(doc_id)
        signature = evidence_signature(
            (e.evidence_id, e.page, e.kind, e.raw_text) for e in evidence
        )
        if (
            facts is None
            or state is None
            or facts.revision != state["revision"]
            or signature != state["evidence_signature"]
        ):
            raise ConflictError(
                f"Run Patent analysis before exporting this document: {document['file_name']}",
                context={"doc_id": doc_id},
            )
        stamps[doc_id] = (facts.revision, signature)
        by_evidence = {e.evidence_id: e for e in evidence}
        entries = {e["entry_id"]: e for e in facts.entries}
        assays = {a["assay_method_id"]: a for a in facts.assay_methods}
        detected = load_detections(root, doc_id)
        candidates = filter_persistable_candidates(
            doc_id, detected[0] if detected else [], warn=False
        )
        by_ref: dict[str, Any] = {}
        saved_structures: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            saved = repos.molecules.find_row(candidate.canonical_smiles)
            if saved:
                saved_structures[candidate.canonical_smiles] = saved
            for ref in (
                candidate.mol_id,
                candidate.canonical_smiles,
                (saved or {}).get("mol_id"),
            ):
                if ref:
                    by_ref[ref] = candidate
        records = measurement_records(
            doc_id=doc_id,
            run_id=facts.run_id,
            measurements=facts.measurements,
            assay_methods=facts.assay_methods,
        )
        if len(records) != len(facts.measurements):
            raise ConflictError(
                f"Duplicate or missing reading IDs; rerun Patent analysis: {doc_id}"
            )
        document_rows: list[dict[str, Any]] = []
        for measurement, record in zip(facts.measurements, records, strict=True):
            entry = entries.get(record.entry_id or "", {})
            assay = assays.get(record.assay_method_id or "", {})
            refs = {
                ref
                for ref in (measurement.get("mol_id"), entry.get("entity_id"))
                if ref
            }
            structures = [by_ref.get(ref) for ref in refs]
            identities = {s.canonical_smiles for s in structures if s is not None}
            reasons: list[str] = []
            structure = structures[0] if structures else None
            if len(identities) > 1 or (
                len(refs) > 1 and any(s is None for s in structures)
            ):
                reasons.append("conflicting_structure_references")
                structure = None
            elif structure is None or any(s is None for s in structures):
                reasons.append("structure_not_resolved")
                structure = None
            saved = (
                saved_structures.get(structure.canonical_smiles, {})
                if structure
                else {}
            )
            if (
                saved.get("status") == "rejected"
                or saved.get("review_status") == "rejected"
            ):
                reasons.append("structure_rejected")
            identity_changed = bool(
                structure
                and saved
                and saved.get("canonical_smiles") != structure.canonical_smiles
            )
            if identity_changed:
                reasons.append("structure_identity_changed")
            structure_ids = (
                sorted({d.evidence_id for d in structure.detections if d.evidence_id})
                if structure
                else []
            )
            groups = {
                "reading": record.evidence_ids,
                "structure": structure_ids,
                "entry": list(entry.get("evidence_ids") or []),
                "assay": list(assay.get("evidence_ids") or []),
            }
            for kind, ids in groups.items():
                if (
                    kind in ("reading", "structure")
                    or (kind == "entry" and record.entry_id)
                    or (kind == "assay" and record.assay_method_id)
                ) and not ids:
                    reasons.append(f"missing_{kind}_evidence")
                if any(eid not in by_evidence for eid in ids):
                    reasons.append(f"invalid_{kind}_evidence")
            if record.entry_id and not entry:
                reasons.append("entry_not_found")
            if record.assay_method_id and not assay:
                reasons.append("assay_not_found")
            if record.page_num is not None and not any(
                by_evidence[eid].page == record.page_num
                for eid in record.evidence_ids
                if eid in by_evidence
            ):
                reasons.append("reading_page_mismatch")
            if entry.get("review_status") == "rejected":
                reasons.append("entry_rejected")
            row = {
                **record.model_dump(),
                "file_name": document["file_name"],
                "revision": facts.revision,
                "designation": entry.get("label_raw") or record.reference_raw,
                "mol_id": (saved.get("mol_id") or structure.mol_id or None)
                if structure
                else None,
                "canonical_smiles": structure.canonical_smiles
                if structure and not identity_changed
                else None,
                "recognized_smiles": structure.canonical_smiles if structure else None,
                "current_canonical_smiles": saved.get("canonical_smiles"),
                "operator_original": record.provenance["operator_original"],
                "canonical_metric": record.metric[1:]
                if record.scale == "log10" and record.metric
                else record.metric,
                "conditions": assay.get("conditions") or {},
                "review_status": "pending",
                "structure_review_status": saved.get(
                    "review_status", structure.review_status
                )
                if structure
                else None,
                "missing_fields": [
                    key
                    for key, present in {
                        "metric": record.metric,
                        "target": record.target,
                        "species_or_system": record.species,
                        "assay_method": assay,
                        "assay_conditions": assay.get("conditions"),
                        "unit": record.original_unit
                        or record.scale == "log10"
                        or record.measurement_kind != "quantitative",
                    }.items()
                    if not present
                ],
                "reasons": reasons,
                **{f"{kind}_evidence_ids": ids for kind, ids in groups.items()},
            }
            (unresolved if reasons else paired).append(row)
            document_rows.append(row)
        documents.append(
            {
                "doc_id": doc_id,
                "file_name": document["file_name"],
                "revision": facts.revision,
                "evidence_signature": signature,
                "facts": facts.model_dump(exclude={"projection_status"}),
                "evidence": [e.to_dict() for e in evidence],
                "rows": document_rows,
            }
        )

    # Re-extraction or publication during assembly must not mix revisions.
    for doc_id, (revision, signature) in stamps.items():
        state = repos.patent_analysis.load(doc_id)
        evidence = repos.evidence.list(doc_id)
        current = evidence_signature(
            (e.evidence_id, e.page, e.kind, e.raw_text) for e in evidence
        )
        if not state or state["revision"] != revision or current != signature:
            raise ConflictError("Document changed during export; retry the export.")
    dataset = {
        "schema": "mbforge.structure-activity.v1",
        "documents": documents,
        "counts": {
            "matched_pending_review": len(paired),
            "unresolved": len(unresolved),
        },
    }
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("structure_activity.csv", _csv(paired))
        archive.writestr("unresolved.csv", _csv(unresolved))
        archive.writestr(
            "dataset.json",
            json.dumps(dataset, ensure_ascii=False, indent=2, allow_nan=False),
        )
        archive.writestr(
            "README.txt",
            (
                "structure_activity.csv: matched readings, pending scientific review.\n"
                "unresolved.csv: every remaining reading, with explicit reasons. No rows are silently dropped.\n"
                "dataset.json: exact values, committed facts and SQL source evidence.\n"
                "doc_id is the imported PDF SHA-256. Match it to your original file. PDFs are not bundled.\n"
                "Evidence pages are one-based; bboxes use PDF points, bottom-left origin. Table/row/column indexes are zero-based.\n"
                "original_* and metric retain source scale; canonical_* and operator use the converted scale.\n"
                "Known concentration units convert to nM; unknown units remain unchanged; missing units are not invented.\n"
                "Qualitative bins remain qualitative. Different assays/species/conditions are separate rows.\n"
                "missing_fields records absent context; an empty species, assay or condition is unknown, never a match key.\n"
                "Matching and mass consistency do not prove the recognized structure is correct. Review source drawings and assays.\n"
                "If a catalog correction changed identity, canonical_smiles is blank and the reading is unresolved; recognized_smiles and current_canonical_smiles keep both versions.\n"
                "CSV is UTF-8 BOM. Formula-like strings have an apostrophe prefix for spreadsheets; JSON retains exact text.\n"
            ),
        )
    return output.getvalue()

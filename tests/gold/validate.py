"""Validate MBForge gold relation-pair records.

The JSON Schema in ``schema.json`` is the structural contract. This script
adds the cross-field and manifest checks that JSON Schema cannot express
(bbox ordering, key-space consistency, gold-status requirements, document
metadata agreement, unique ids).

Usage:
    uv run python tests/gold/validate.py --self-test
    uv run python tests/gold/validate.py tests/gold/annotations/dev.jsonl

Exit code 0 means every record passed; 1 means at least one failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "manifest.json"

RELATION_TYPES = {
    "exemplified_by",
    "designated_as",
    "reported_as",
    "member_of_genus",
    "claim_scope",
    "prepared_from",
    "salt_of",
    "solvate_of",
    "stereoisomer_of",
    "tautomer_of",
    "formulated_as",
}
GOLD_STATUSES = {"present", "absent", "insufficient_evidence"}
PAGE_ANNOTATIONS = {"exhaustive", "targeted"}
RENDERINGS = {
    "scanned",
    "native",
    "hybrid",
    "ocr_layer",
    "tiff",
    "xml",
    "docx",
    "paper",
}
KEY_SPACES = {
    "example",
    "compound",
    "claim",
    "internal_code",
    "table_row",
    "scheme_node",
    "none",
}
ANCHOR_KINDS = {
    "section_heading",
    "table_row_label",
    "table_cell",
    "caption",
    "prose",
    "scheme_node",
    "claim_text",
    "title",
    "abstract",
}
IDENTITY_LEVELS = {
    "exact_stereo",
    "exact_isotopes",
    "connectivity",
    "parent_after_desalting",
    "tautomer_collapsed",
}
VERIFICATION_STATUSES = {
    "insufficient_evidence",
    "uncorroborated",
    "corroborated",
    "contradicted",
}
CORROBORATION_SOURCES = {
    "ms_mass",
    "label_sequence",
    "geometry_complete",
    "table_complete",
    "name_match",
    "human_confirm",
    "cross_renderer",
    "reaction_balance",
}
RESULTS = {"pass", "fail", "not_run"}
CHEMISTRY_PATTERNS = {
    "example_per_compound",
    "markush_genus",
    "table_only_sar",
    "reaction_scheme",
    "prophetic",
    "formulation",
    "salt_polymorph",
    "biotech_sequence",
    "polymer",
    "no_chemistry",
}
TABLE_FORMS = {
    "none",
    "unknown",
    "simple",
    "split_header",
    "repeated_pairs",
    "merged_cells",
    "target_in_header",
    "rotated",
    "structure_column",
    "cross_page",
    "legend",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bbox_errors(bbox: Any, path: str) -> list[str]:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return [f"{path}: bbox must be a list of four numbers"]
    if not all(_is_number(value) for value in bbox):
        return [f"{path}: bbox values must be numbers"]
    x0, y0, x1, y1 = bbox
    errors: list[str] = []
    if min(x0, y0, x1, y1) < 0:
        errors.append(f"{path}: bbox has a negative coordinate")
    if x0 > x1:
        errors.append(f"{path}: bbox x0 > x1")
    if y0 > y1:
        errors.append(f"{path}: bbox y0 > y1")
    return errors


def _chemical_errors(item: Any, path: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{path}: must be an object"]
    errors: list[str] = []
    kind = item.get("kind")
    if kind not in {"molecule", "scaffold"}:
        errors.append(f"{path}.kind: must be 'molecule' or 'scaffold'")
    if kind == "molecule" and not (item.get("smiles") or item.get("inchikey")):
        errors.append(f"{path}: a molecule requires smiles or inchikey")
    if kind == "scaffold" and not (item.get("esmiles") or item.get("scaffold_id")):
        errors.append(f"{path}: a scaffold requires esmiles or scaffold_id")
    if "identity_level" in item and item["identity_level"] not in IDENTITY_LEVELS:
        errors.append(
            f"{path}.identity_level: unknown value {item['identity_level']!r}"
        )
    if "bbox" in item:
        errors.extend(_bbox_errors(item["bbox"], f"{path}.bbox"))
    if "page" in item and (not isinstance(item["page"], int) or item["page"] < 1):
        errors.append(f"{path}.page: must be a positive integer")
    if "variables" in item:
        if not isinstance(item["variables"], list):
            errors.append(f"{path}.variables: must be a list")
        else:
            for index, variable in enumerate(item["variables"]):
                if not isinstance(variable, dict):
                    errors.append(f"{path}.variables[{index}]: must be an object")
                    continue
                if not variable.get("label"):
                    errors.append(f"{path}.variables[{index}].label: required")
                if not variable.get("definition_raw"):
                    errors.append(f"{path}.variables[{index}].definition_raw: required")
    return errors


def _verification_errors(verification: Any, path: str) -> list[str]:
    if not isinstance(verification, dict):
        return [f"{path}: must be an object"]
    errors: list[str] = []
    status = verification.get("status")
    if status not in VERIFICATION_STATUSES:
        errors.append(f"{path}.status: unknown value {status!r}")
    sources = verification.get("sources")
    if not isinstance(sources, list):
        errors.append(f"{path}.sources: must be a list")
        return errors
    passes = 0
    fails = 0
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"{path}.sources[{index}]: must be an object")
            continue
        if source.get("source") not in CORROBORATION_SOURCES:
            errors.append(f"{path}.sources[{index}].source: unknown value")
        result = source.get("result")
        if result not in RESULTS:
            errors.append(f"{path}.sources[{index}].result: unknown value")
        elif result == "pass":
            passes += 1
        elif result == "fail":
            fails += 1
    if status == "corroborated" and passes == 0:
        errors.append(f"{path}: corroborated requires at least one pass")
    if status == "contradicted" and fails == 0:
        errors.append(f"{path}: contradicted requires at least one fail")
    if status == "insufficient_evidence" and passes:
        errors.append(f"{path}: insufficient_evidence cannot carry a pass")
    return errors


def validate_record(record: Any, docs: dict[str, dict[str, Any]]) -> list[str]:
    """Return every violation in one record. An empty list means valid."""
    if not isinstance(record, dict):
        return ["record: must be a JSON object"]

    errors: list[str] = []
    required = [
        "gold_id",
        "schema_version",
        "doc",
        "page_annotation",
        "anchor",
        "relation_type",
        "gold_status",
        "evidence_ids",
        "geometry_complete",
        "annotation",
    ]
    for key in required:
        if key not in record:
            errors.append(f"record: missing {key!r}")

    if record.get("schema_version") != 1:
        errors.append("schema_version: must be 1")

    if not isinstance(record.get("gold_id"), str) or not record["gold_id"]:
        errors.append("gold_id: must be a non-empty string")

    doc = record.get("doc")
    if not isinstance(doc, dict):
        errors.append("doc: must be an object")
    else:
        doc_id = doc.get("doc_id")
        if not isinstance(doc_id, str) or len(doc_id) != 64:
            errors.append("doc.doc_id: must be a 64-character SHA-256 hex string")
        elif any(character not in "0123456789abcdef" for character in doc_id):
            errors.append("doc.doc_id: must be lowercase hex")
        elif doc_id not in docs:
            errors.append(f"doc.doc_id: {doc_id} is not in the manifest")
        else:
            manifest_doc = docs[doc_id]
            for field in ("jurisdiction", "kind", "language", "rendering"):
                if doc.get(field) != manifest_doc.get(field):
                    errors.append(
                        f"doc.{field}: {doc.get(field)!r} does not match the manifest "
                        f"({manifest_doc.get(field)!r})"
                    )
        for field in ("file_name", "jurisdiction", "kind", "language"):
            if not isinstance(doc.get(field), str) or not doc.get(field):
                errors.append(f"doc.{field}: must be a non-empty string")
        if doc.get("rendering") not in RENDERINGS:
            errors.append(f"doc.rendering: unknown value {doc.get('rendering')!r}")
        patterns = doc.get("chemistry_pattern")
        if not isinstance(patterns, list) or not patterns:
            errors.append("doc.chemistry_pattern: must be a non-empty list")
        elif any(pattern not in CHEMISTRY_PATTERNS for pattern in patterns):
            errors.append("doc.chemistry_pattern: unknown value")
        forms = doc.get("table_form")
        if not isinstance(forms, list):
            errors.append("doc.table_form: must be a list")
        elif any(form not in TABLE_FORMS for form in forms):
            errors.append("doc.table_form: unknown value")

    if record.get("page_annotation") not in PAGE_ANNOTATIONS:
        errors.append("page_annotation: unknown value")

    anchor = record.get("anchor")
    if not isinstance(anchor, dict):
        errors.append("anchor: must be an object")
    else:
        if anchor.get("kind") not in ANCHOR_KINDS:
            errors.append(f"anchor.kind: unknown value {anchor.get('kind')!r}")
        if anchor.get("key_space") not in KEY_SPACES:
            errors.append(
                f"anchor.key_space: unknown value {anchor.get('key_space')!r}"
            )
        if not isinstance(anchor.get("label_raw"), str) or not anchor["label_raw"]:
            errors.append("anchor.label_raw: must be a non-empty string")
        if not isinstance(anchor.get("label_key"), str) or not anchor["label_key"]:
            errors.append("anchor.label_key: must be a non-empty string")
        if not isinstance(anchor.get("page"), int) or anchor["page"] < 1:
            errors.append("anchor.page: must be a positive integer")
        if "bbox" in anchor:
            errors.extend(_bbox_errors(anchor["bbox"], "anchor.bbox"))
        else:
            errors.append("anchor.bbox: required")
        if not isinstance(anchor.get("evidence_id"), str) or not anchor["evidence_id"]:
            errors.append("anchor.evidence_id: must be a non-empty string")
        if anchor.get("key_space") == "example" and not str(
            anchor.get("label_key", "")
        ).startswith("@example:"):
            errors.append("anchor.label_key: example space must start with '@example:'")
        if anchor.get("key_space") == "compound" and str(
            anchor.get("label_key", "")
        ).startswith("@example:"):
            errors.append(
                "anchor.label_key: compound space cannot start with '@example:'"
            )

    if record.get("relation_type") not in RELATION_TYPES:
        errors.append(f"relation_type: unknown value {record.get('relation_type')!r}")
    if "example_status" in record and record["example_status"] not in {
        "exemplified",
        "prophetic",
        "unknown",
    }:
        errors.append("example_status: unknown value")
    if record.get("gold_status") not in GOLD_STATUSES:
        errors.append(f"gold_status: unknown value {record.get('gold_status')!r}")

    evidence_ids = record.get("evidence_ids")
    if not isinstance(evidence_ids, list):
        errors.append("evidence_ids: must be a list")
    elif len(evidence_ids) != len(set(evidence_ids)):
        errors.append("evidence_ids: must not contain duplicates")
    elif any(not isinstance(item, str) or not item for item in evidence_ids):
        errors.append("evidence_ids: every entry must be a non-empty string")

    if not isinstance(record.get("geometry_complete"), bool):
        errors.append("geometry_complete: must be a boolean")

    if "subject" in record:
        errors.extend(_chemical_errors(record["subject"], "subject"))
    if "object" in record:
        errors.extend(_chemical_errors(record["object"], "object"))

    annotation = record.get("annotation")
    if not isinstance(annotation, dict):
        errors.append("annotation: must be an object")
    else:
        if (
            not isinstance(annotation.get("annotator"), str)
            or not annotation["annotator"]
        ):
            errors.append("annotation.annotator: must be a non-empty string")
        if not isinstance(annotation.get("version"), int) or annotation["version"] < 1:
            errors.append("annotation.version: must be a positive integer")
        if not isinstance(annotation.get("created"), str) or not annotation["created"]:
            errors.append("annotation.created: must be a date string")
        adjudicator = annotation.get("adjudicator")
        if adjudicator is not None and not isinstance(adjudicator, str):
            errors.append("annotation.adjudicator: must be a string or null")

    gold_status = record.get("gold_status")
    if gold_status == "present":
        if "subject" not in record and "object" not in record:
            errors.append("present record: requires subject or object")
        if not evidence_ids:
            errors.append("present record: requires at least one evidence_id")
        if record.get("geometry_complete") is not True:
            errors.append("present record: geometry_complete must be true")
        if "verification" not in record:
            errors.append("present record: verification is required")
        else:
            errors.extend(_verification_errors(record["verification"], "verification"))
    elif gold_status == "absent":
        if record.get("page_annotation") != "exhaustive":
            errors.append("absent record: page_annotation must be exhaustive")
        if "subject" in record or "object" in record:
            errors.append("absent record: must not carry a subject or object")
    elif gold_status == "insufficient_evidence":
        if "verification" in record:
            verification = record["verification"]
            if isinstance(verification, dict) and verification.get("status") != (
                "insufficient_evidence"
            ):
                errors.append(
                    "insufficient_evidence record: verification.status must be "
                    "insufficient_evidence"
                )

    return errors


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise SystemExit(f"{path}: documents must be a list")
    docs: dict[str, dict[str, Any]] = {}
    for document in documents:
        doc_id = document.get("doc_id")
        if not isinstance(doc_id, str) or len(doc_id) != 64:
            raise SystemExit(f"{path}: invalid doc_id {doc_id!r}")
        if doc_id in docs:
            raise SystemExit(f"{path}: duplicate doc_id {doc_id}")
        docs[doc_id] = document
    return docs


def validate_file(path: Path, docs: dict[str, dict[str, Any]]) -> tuple[int, int]:
    total = 0
    invalid = 0
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        total += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"{path}:{line_number}: invalid JSON: {exc}")
            invalid += 1
            continue
        errors = validate_record(record, docs)
        gold_id = record.get("gold_id")
        if isinstance(gold_id, str):
            if gold_id in seen_ids:
                errors.append(f"gold_id: duplicate {gold_id!r}")
            seen_ids.add(gold_id)
        if errors:
            invalid += 1
            print(f"{path}:{line_number}: {len(errors)} error(s)")
            for error in errors:
                print(f"  - {error}")
    return total, invalid


def _valid_record() -> dict[str, Any]:
    doc_id = "0" * 64
    return {
        "gold_id": "self-test:p1:section-heading:exemplified_by:primary",
        "schema_version": 1,
        "doc": {
            "doc_id": doc_id,
            "file_name": "TEST.pdf",
            "jurisdiction": "CN",
            "kind": "A",
            "language": "zh",
            "translation": "none",
            "rendering": "scanned",
            "chemistry_pattern": ["example_per_compound"],
            "table_form": ["simple"],
        },
        "page_annotation": "exhaustive",
        "anchor": {
            "kind": "section_heading",
            "key_space": "example",
            "label_raw": "实施例1",
            "label_key": "@example:1",
            "page": 1,
            "bbox": [10, 10, 100, 30],
            "evidence_id": "ev-1",
        },
        "subject": {
            "kind": "molecule",
            "smiles": "CCO",
            "identity_level": "connectivity",
            "page": 1,
            "bbox": [10, 40, 120, 140],
            "evidence_id": "ev-2",
        },
        "relation_type": "exemplified_by",
        "example_status": "exemplified",
        "gold_status": "present",
        "verification": {
            "status": "corroborated",
            "sources": [
                {"source": "ms_mass", "result": "pass", "detail": "within 0.6 Da"}
            ],
        },
        "evidence_ids": ["ev-1", "ev-2"],
        "geometry_complete": True,
        "annotation": {
            "annotator": "A",
            "adjudicator": None,
            "version": 1,
            "created": "2026-10-23",
        },
    }


def self_test() -> int:
    doc_id = "0" * 64
    docs = {
        doc_id: {
            "doc_id": doc_id,
            "jurisdiction": "CN",
            "kind": "A",
            "language": "zh",
            "rendering": "scanned",
        }
    }
    valid = _valid_record()
    failures: list[str] = []

    errors = validate_record(valid, docs)
    if errors:
        failures.append(f"valid record rejected: {errors}")

    broken_geometry = json.loads(json.dumps(valid))
    broken_geometry["geometry_complete"] = False
    if not validate_record(broken_geometry, docs):
        failures.append("geometry_complete=false was accepted for a present record")

    broken_absent = json.loads(json.dumps(valid))
    broken_absent["gold_status"] = "absent"
    broken_absent.pop("subject", None)
    broken_absent["page_annotation"] = "targeted"
    if not validate_record(broken_absent, docs):
        failures.append("targeted absent record was accepted")

    broken_key = json.loads(json.dumps(valid))
    broken_key["anchor"]["key_space"] = "compound"
    if not validate_record(broken_key, docs):
        failures.append("example label in compound key space was accepted")

    broken_manifest = json.loads(json.dumps(valid))
    broken_manifest["doc"]["rendering"] = "native"
    if not validate_record(broken_manifest, docs):
        failures.append("rendering mismatch with the manifest was accepted")

    if failures:
        for failure in failures:
            print(f"SELF-TEST FAIL: {failure}")
        return 1
    print("SELF-TEST OK: valid record accepted; 4 invalid variants rejected")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", nargs="?", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check-manifest", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.check_manifest:
        docs = load_manifest(args.manifest)
        print(f"manifest: {len(docs)} documents")
        return 0

    if args.annotations is None:
        parser.print_help()
        return 2

    docs = load_manifest(args.manifest)
    print(f"manifest: {len(docs)} documents")
    total, invalid = validate_file(args.annotations, docs)
    print(f"records: {total - invalid} valid, {invalid} invalid")
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())

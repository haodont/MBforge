"""Generic CLI entrypoint for the golden evaluation suite.

Usage::

    python -m tests.eval.run_eval \
        --golden US20260027089A1 \
        --candidate path/to/candidate.json \
        --output path/to/report.json

The candidate JSON may carry any of the keys ``results`` (activity
extraction) and ``molecules`` (structure detection). Missing keys are
treated as empty. The report aggregates every metric declared in
``activity``, ``molecule``, ``markush``, and ``stability``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "test_data" / "golden"

SUPPORTED_GOLDENS = {
    "US20260027089A1",
    "WO2026037254A1",
}


def _load_golden(dataset_id: str) -> dict:
    path = GOLDEN_ROOT / dataset_id / "reference.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_candidate(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a pipeline dump against a golden reference."
    )
    parser.add_argument(
        "--golden",
        choices=sorted(SUPPORTED_GOLDENS),
        required=True,
        help="Golden dataset id (folder name under test_data/golden/).",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="JSON dump produced by the pipeline.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the aggregated report.",
    )
    args = parser.parse_args(argv)

    golden = _load_golden(args.golden)
    candidate = _load_candidate(args.candidate)

    from tests.eval._lib.activity import score_activity
    from tests.eval._lib.golden import validate_reference
    from tests.eval._lib.markush import score_markush
    from tests.eval._lib.molecule import score_molecules
    from tests.eval._lib.stability import validate_run_summary

    golden_validation = validate_reference(golden, expected_folder=args.golden)
    if not golden_validation.valid:
        raise ValueError(
            f"Invalid golden reference {args.golden}: "
            + "; ".join(golden_validation.errors)
        )

    # Pending rows are visible in the report but are excluded from the primary
    # calibration denominator until manual annotation is complete.
    scored_activity_rows = [
        row
        for row in golden["activity_rows"]
        if row.get("annotation_status") == "verified"
    ]
    activity_metrics = score_activity(scored_activity_rows, candidate).as_dict()
    molecule_golden = golden.get("concrete_molecule_anchors") or golden["activity_rows"]
    molecule_golden = [
        row for row in molecule_golden if row.get("annotation_status") == "verified"
    ]
    markush_golden = [
        row
        for row in golden["markush_anchors"]
        if row.get("annotation_status") == "verified"
    ]
    molecule_metrics = score_molecules(molecule_golden, candidate).as_dict()
    markush_metrics = score_markush(markush_golden, candidate).as_dict()
    stability_missing = validate_run_summary(candidate.get("run_summary", {}))

    report = {
        "golden_reference": {
            "dataset_id": golden.get("dataset_id"),
            "annotation_status": golden.get("annotation_status"),
            "schema_version": golden.get("schema_version"),
            "activity_rows": len(golden.get("activity_rows", [])),
            "activity_rows_scored": len(scored_activity_rows),
            "markush_anchors": len(golden.get("markush_anchors", [])),
            "markush_anchors_scored": len(markush_golden),
            "concrete_anchors": len(golden.get("concrete_molecule_anchors", [])),
            "concrete_anchors_scored": len(molecule_golden),
        },
        "golden_validation": golden_validation.as_dict(),
        "scoring_policy": {
            "primary_annotation_statuses": ["verified"],
            "pending_rows_excluded_from_primary_metrics": True,
        },
        "activity": activity_metrics,
        "molecule": molecule_metrics,
        "markush": markush_metrics,
        "stability": {
            "missing_metrics": stability_missing,
            "complete": not stability_missing,
        },
    }

    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())

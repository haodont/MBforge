"""Export the Node-facing patent-analysis contract schema.

The sidecar reads the exported, versioned bundle instead of a hand-maintained
second copy of the draft fields. Regenerate after any change to
:mod:`mbforge.contracts.patent`:

    uv run python -m mbforge.contracts.schema_export

The committed artifact is ``agent/schemas/patent-analysis.v1.json`` (source
checkouts only; this tool does not do anything useful in an installed wheel).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mbforge.contracts.patent import (
    GAP_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    PatentAnalysisSnapshot,
    PatentConflict,
    PatentDecision,
    PatentDraft,
    PatentGap,
    PatentGapAnswer,
)

#: Models exported to Node, in bundle order.
EXPORTED_MODELS: dict[str, type] = {
    "PatentDraft": PatentDraft,
    "PatentConflict": PatentConflict,
    "PatentDecision": PatentDecision,
    "PatentAnalysisSnapshot": PatentAnalysisSnapshot,
}

#: The gap-answer path: one bounded gap in, one bounded answer out. Nested item
#: models travel in the schema's ``$defs``.
GAP_EXPORTED_MODELS: dict[str, type] = {
    "PatentGap": PatentGap,
    "PatentGapAnswer": PatentGapAnswer,
}


def build_bundle() -> dict[str, Any]:
    """Return the versioned schema bundle (deterministic, no I/O)."""
    return _bundle(PROTOCOL_VERSION, EXPORTED_MODELS)


def build_gap_bundle() -> dict[str, Any]:
    """Return the gap-answer schema bundle (deterministic, no I/O)."""
    return _bundle(GAP_PROTOCOL_VERSION, GAP_EXPORTED_MODELS)


def _bundle(version: str, models: dict[str, type]) -> dict[str, Any]:
    return {
        "protocol_version": version,
        "generated_from": "mbforge.contracts.patent",
        "models": {name: model.model_json_schema() for name, model in models.items()},
    }


def default_output_path() -> Path:
    """``<repo>/agent/schemas/patent-analysis.v1.json`` for a source checkout."""
    return _schema_dir() / f"patent-analysis.v{PROTOCOL_VERSION}.json"


def default_gap_output_path() -> Path:
    """``<repo>/agent/schemas/patent-gap.v2.json`` for a source checkout."""
    return _schema_dir() / f"patent-gap.v{GAP_PROTOCOL_VERSION}.json"


def _schema_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "agent" / "schemas"


def write_bundle(path: Path, bundle: dict[str, Any] | None = None) -> Path:
    """Write *bundle* to *path* (parents created) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            bundle if bundle is not None else build_bundle(),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path for the draft bundle "
        "(defaults to agent/schemas/patent-analysis.v1.json).",
    )
    parser.add_argument(
        "--gaps",
        action="store_true",
        help="Write the gap-answer bundle instead of the draft bundle.",
    )
    args = parser.parse_args()
    if args.gaps:
        print(
            f"Wrote {write_bundle(args.out or default_gap_output_path(), build_gap_bundle())}"
        )
        return
    print(f"Wrote {write_bundle(args.out or default_output_path())}")


if __name__ == "__main__":
    main()

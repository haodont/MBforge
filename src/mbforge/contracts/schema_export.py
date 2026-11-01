"""Export the Node-facing patent gap-answer schema.

The sidecar loads the exported, versioned bundle instead of a hand-maintained
second copy of the gap fields. Regenerate after any change to
:mod:`mbforge.contracts.patent`:

    uv run python -m mbforge.contracts.schema_export

The committed artifact is ``agent/schemas/patent-gap.v2.json`` (source
checkouts only; this tool does not do anything useful in an installed wheel).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mbforge.contracts.patent import (
    GAP_PROTOCOL_VERSION,
    PatentGap,
    PatentGapAnswer,
)

#: The gap-answer path: one bounded gap in, one bounded answer out.
GAP_EXPORTED_MODELS: dict[str, type] = {
    "PatentGap": PatentGap,
    "PatentGapAnswer": PatentGapAnswer,
}


def build_gap_bundle() -> dict[str, Any]:
    """Return the gap-answer schema bundle (deterministic, no I/O)."""
    return {
        "protocol_version": GAP_PROTOCOL_VERSION,
        "generated_from": "mbforge.contracts.patent",
        "models": {
            name: model.model_json_schema()
            for name, model in GAP_EXPORTED_MODELS.items()
        },
    }


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
            bundle if bundle is not None else build_gap_bundle(),
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
        help="Output path for the gap bundle "
        "(defaults to agent/schemas/patent-gap.v2.json).",
    )
    args = parser.parse_args()
    print(f"Wrote {write_bundle(args.out or default_gap_output_path())}")


if __name__ == "__main__":
    main()

"""Guard the dependency direction of the five-layer source tree.

Layers: ``api -> service``; ``service``/``db``/``api`` may depend on the
``foundation`` support package but never on a layer above them. ``domain`` is
pure and may not import any other business layer (nor the model inference
subpackage).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE_ROOT = Path(__file__).parents[3] / "src" / "mbforge"
_FORBIDDEN_IMPORTS = {
    "domain": (
        "mbforge.service",
        "mbforge.db",
        "mbforge.api",
        "mbforge.server",
        "mbforge.foundation.inference",
    ),
    "db": ("mbforge.api", "mbforge.server"),
    "service": ("mbforge.db", "mbforge.api", "mbforge.server"),
    "api": ("mbforge.db", "mbforge.server"),
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_layer_boundaries_respect_dependency_direction() -> None:
    violations: list[str] = []
    for layer, forbidden in _FORBIDDEN_IMPORTS.items():
        for path in (_SOURCE_ROOT / layer).rglob("*.py"):
            for imported in _imports(path):
                if any(
                    imported == prefix or imported.startswith(f"{prefix}.")
                    for prefix in forbidden
                ):
                    violations.append(f"{path}: {imported}")
    assert violations == []

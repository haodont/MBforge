"""Guard the dependency direction of the reorganized source tree."""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE_ROOT = Path(__file__).parents[3] / "src" / "mbforge"
_FORBIDDEN_IMPORTS = {
    "domain": ("mbforge.application", "mbforge.adapters", "mbforge.interfaces"),
    "application": ("mbforge.adapters", "mbforge.interfaces"),
    "interfaces": ("mbforge.adapters",),
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


def test_layer_boundaries_do_not_import_outward_adapters() -> None:
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
